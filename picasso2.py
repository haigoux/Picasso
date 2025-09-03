import signal
import time
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import json
import os
import subprocess
import numpy as np
import pyvirtualcam
from termcolor import colored
from colorama import init
import sys
import cv2
import threading
import asyncio
init()

class Logger:
    def __init__(self, prefix):
        self.prefix = prefix

    def log(self, message):
        print(colored(f"[{self.prefix}] {message}", "cyan"))

    def warn(self, message):
        print(colored(f"[{self.prefix}] {message}", "yellow"))

    def error(self, message):
        print(colored(f"[{self.prefix}] {message}", "red"))

    def debug(self, message):
        print(colored(f"[{self.prefix}] {message}", "magenta"))

LOGS = Logger("Picasso")
# Get config or make if not present
config_path = os.path.expanduser("~/.config/picasso/config.json")
default_config = {
    "resolution": "1280x720", # previews, recordings, pictures
    "fps": 30, # ffmpeg argument
    "encoding_format": "libx264", # ffmpeg argument
    "usb_mode": False, # Automatically save to plugged in USB storage device
    "usb_path": "/media/usb1",
    "other_path": "~/",
    "preview_quality": 25, # preview quality
    "camera_device": "/dev/video0", # Default camera device
    "virtual_device": {
        "name": "PicassoVirtCam",
        "device": "/dev/video40"
    }
}
config = None

if not os.path.exists(config_path):
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(default_config, f, indent=4)
    LOGS.log(f"Created default config at {config_path}")
    config = default_config
else:
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except json.JSONDecodeError:
        LOGS.error(f"Config file at {config_path} is not valid JSON")
        if input("Use default config? (y/n): ").lower() == "y":
            config = default_config
        else:
            sys.exit(1)
    except Exception as e:
        LOGS.error(f"Error loading config file at {config_path}: {e}")
        if input("Use default config? (y/n): ").lower() == "y":
            config = default_config
        else:
            sys.exit(1)
    finally:
        pass

for key in default_config:
    if key not in config:
        LOGS.warn(f"Missing config option for: {key}, using default: {default_config[key]}")
        config[key] = default_config[key]

class CameraInterface:
    def init_folder_struct(self):
        usb_path = config["usb_path"]
        if config['usb_mode'] and not usb_path:
            self.logger.error(f"usb_mode is True, but usb_path is null. Edit in config located in {config_path}")
            sys.exit(1)
        if config["usb_mode"] and usb_path and os.path.exists(usb_path):
            # root/picasso/
            if not os.path.exists(os.path.join(usb_path, "picasso")):
                os.makedirs(os.path.join(usb_path, "picasso"), exist_ok=True)

            # root/picasso/videos
            if not os.path.exists(os.path.join(usb_path, "picasso", "videos")):
                os.makedirs(os.path.join(usb_path, "picasso", "videos"), exist_ok=True)

            # root/picasso/pictures
            if not os.path.exists(os.path.join(usb_path, "picasso", "pictures")):
                os.makedirs(os.path.join(usb_path, "picasso", "pictures"), exist_ok=True)

            return os.path.join(usb_path, "picasso")
        
        if config['usb_mode'] == False:
            other_path = os.path.expanduser(config["other_path"])
            if not os.path.exists(other_path):
                os.makedirs(other_path, exist_ok=True)
            # root/picasso/
            if not os.path.exists(os.path.join(other_path, "picasso")):
                os.makedirs(os.path.join(other_path, "picasso"), exist_ok=True)

            # root/picasso/videos
            if not os.path.exists(os.path.join(other_path, "picasso", "videos")):
                os.makedirs(os.path.join(other_path, "picasso", "videos"), exist_ok=True)

            # root/picasso/pictures
            if not os.path.exists(os.path.join(other_path, "picasso", "pictures")):
                os.makedirs(os.path.join(other_path, "picasso", "pictures"), exist_ok=True)

            return os.path.join(other_path, "picasso")

    def __init__(self):
        self.logger = Logger('CameraInterface')
        self.metadata = {
            "recording": False,
            "start_time": None,
            "end_time": None,
            "fps": config["fps"],
            "resolution": config["resolution"]
        }
        self._black_frame = np.zeros((int(config["resolution"].split("x")[1]), int(config["resolution"].split("x")[0]), 3), dtype=np.uint8)
        self._frame_buffer = []
        self._cur_frame = None
        self._ffmpeg_pid = None
        self.root = self.init_folder_struct()
        # verify we can access the specified video device
        if subprocess.run(["v4l2-ctl", "--device", config["camera_device"], "--all"], capture_output=True).returncode != 0:
            self.logger.error(f"Cannot access camera device {config['camera_device']}")
            sys.exit(1)

        if subprocess.call(["sudo", "modprobe", "-r", "v4l2loopback"]) != 0:
            self.logger.error("Failed to unload v4l2loopback module")
            sys.exit(1)

        # create the virtual camera modprobe
        subprocess.run(["sudo", "modprobe", "v4l2loopback", "devices=1", "video_nr=40", f"card_label={config['virtual_device']['name']}", "exclusive_caps=1", "output=1"])
        # verify we can access the virtual camera device
        if subprocess.run(["v4l2-ctl", "--device", config["virtual_device"]["device"], "--all"], capture_output=True).returncode != 0:
            self.logger.error(f"Cannot access virtual camera device {config['virtual_device']['device']}")
            sys.exit(1)

        self.logger.log("Successfully created virtual camera")
        try:
            self.cap = cv2.VideoCapture(config["camera_device"]) 
        except Exception as e:
            self.logger.error(f"Failed to create video capture: {e}")
            sys.exit(1)

        try:
            # set fps and resolution
            self.cap.set(cv2.CAP_PROP_FPS, config["fps"])
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["resolution"].split("x")[0]))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["resolution"].split("x")[1]))
        except Exception as e:
            self.logger.error(f"Failed to set video capture properties: {e}")
            sys.exit(1)

    def start(self):
        asyncio.run(self.recv_frame())

    def makeIfNotDir(self, dir_path):
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

    def getNextVideoPath(self):
        video_dir = os.path.join(self.root, "videos")
        # picasso/videos/MonthFullNameYYYY/dayNumberHHMMSS.avi
        now = time.localtime()
        month_full_name = time.strftime("%B", now)
        day_number = time.strftime("%d", now)
        time_str = time.strftime("%I_%M_%S_%p", now)
        video_path = os.path.join(video_dir, f"{month_full_name}{now.tm_year}/{day_number}__{time_str}.avi")
        if not os.path.exists(video_path):
            self.makeIfNotDir(os.path.dirname(video_path))
        return video_path

    def getNextPicturePath(self):
        picture_dir = os.path.join(self.root, "pictures")
        # picasso/pictures/MonthFullNameYYYY/dayNumberHHMMSS.jpg
        now = time.localtime()
        month_full_name = time.strftime("%B", now)
        day_number = time.strftime("%d", now)
        time_str = time.strftime("%I_%M_%S_%p", now)
        picture_path = os.path.join(picture_dir, f"{month_full_name}{now.tm_year}/{day_number}__{time_str}.jpg")
        if not os.path.exists(picture_path):
            self.makeIfNotDir(os.path.dirname(picture_path))
        return picture_path

    def start_recording(self):
        self.metadata["recording"] = True
        self.metadata["start_time"] = time.time()
        self.logger.log("Started recording")
        # ffmpeg -f v4l2 -video_size 1280x800 -i /dev/video0 -codec:v h264_omx -b:v 2048k webcam.mkv
        proc = subprocess.Popen([
            "ffmpeg",
            "-f", "v4l2",
            "-video_size", config["resolution"],
            "-i", "/dev/video40",
            "-c:v", "h264_omx",
            "-b:v", "2048k",
            self.getNextVideoPath()
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) # TODO: add to log files l8r m8
        self._ffmpeg_pid = proc.pid

    def stop_recording(self):
        self.metadata["recording"] = False
        self.metadata["end_time"] = time.time()
        self.logger.log("Stopped recording")
        if self._ffmpeg_pid:
            os.kill(self._ffmpeg_pid, signal.SIGTERM)

    async def recv_frame(self):
        self.logger.log("Starting frame receiver")
        with pyvirtualcam.Camera(width=int(config["resolution"].split("x")[0]), height=int(config["resolution"].split("x")[1]), fps=config["fps"], device=config["virtual_device"]["device"], print_fps=False) as vcam:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    self.logger.error("Failed to read frame from camera")
                    self._cur_frame = self._black_frame
                else:
                    self._cur_frame = frame
                await self.on_frame(frame, vcam)

    async def send_vframe(self, frame: np.ndarray, vcam: pyvirtualcam.Camera):
        vcam.send(frame)
        vcam.sleep_until_next_frame()

    async def on_frame(self, frame: np.ndarray, vcam: pyvirtualcam.Camera):
        # first rescale just in case
        frame = cv2.resize(frame, (int(config["resolution"].split("x")[0]), int(config["resolution"].split("x")[1])))
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        await self.send_vframe(frame, vcam)

    # OLD EXAMPLE
    # async def gen_frames(request: Request):
    #     while await request.is_disconnected() is False:
    #         _, buffer = cv2.imencode('.jpg', window.rescaled_frame)
    #         yield (b'--frame\r\n'
    #                b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

    async def _get_web_stream(self, request: Request):
        import time
        last_frame_time = 0
        target_fps = 60  # Lower FPS for smoother streaming and HALF the resolution
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), config["preview_quality"]]
        # half
        while await request.is_disconnected() is False:
            now = time.time()
            if now - last_frame_time < 1.0 / target_fps:
                await asyncio.sleep(0.01)
                continue
            last_frame_time = now
            frame = self._cur_frame if self._cur_frame is not None else self._black_frame
            frame = cv2.resize(frame, (frame.shape[1] // 2, frame.shape[0] // 2))
            ret, buffer = cv2.imencode('.jpg', frame, encode_params)
            if not ret:
                await asyncio.sleep(0.01)
                continue
            yield (b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
app = FastAPI(docs_url=None)
camera = CameraInterface()

def run_camera():
    asyncio.run(camera.recv_frame())
threading.Thread(target=run_camera, daemon=True).start()

@app.get("/stream")
async def stream(req: Request):
    return StreamingResponse(camera._get_web_stream(req), media_type='multipart/x-mixed-replace; boundary=frame')

@app.post("/capture")
async def capture():
    image = camera.capture_image()
    return JSONResponse(content={"image": image})
