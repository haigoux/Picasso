from datetime import timedelta
import shutil
import signal
import time
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
# cors
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import subprocess
import numpy as np
import pyvirtualcam
import datetime
from termcolor import colored
from colorama import init
import sys
import cv2
import threading
import asyncio
import psutil
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
    "passcode": "1234", # simple passcode to stop/start recording and take pictures
    "secure": True, # if true, require passcode to stop/start recording and take pictures
    "virtual_device": {
        "name": "PicassoVirtCam",
        "device": "/dev/video40"
    },
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
        sys.exit(1)

update_config = False
for key in default_config:
    if key not in config:
        LOGS.warn(f"Missing config option for: {key}, using default: {default_config[key]}")
        config[key] = default_config[key]
        update_config = True
delkeys = []
for key in config:
    if key not in default_config:
        LOGS.warn(f"Unknown config option found: {key}, removing it")
        delkeys.append(key)
        update_config = True
for key in delkeys:
    del config[key]

if update_config:
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
        LOGS.log(f"Updated config at {config_path} with missing default values")
    except Exception as e:
        LOGS.error(f"Failed to update config at {config_path}: {e}")
        sys.exit(1)

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
            "resolution": config["resolution"],
            "storage_usage": {
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0
            },
            "memory_usage": {
                "total_bytes": 0,
                "used_bytes": 0,
                "free_bytes": 0
            },
            "saving": {
                "complete": False,
                "total_bytes": 0,
                "moved_bytes": 0,
            }
        }
        self._failed_frame_count = 0
        self._temp_output_path = None
        self._black_frame = np.zeros((int(config["resolution"].split("x")[1]), int(config["resolution"].split("x")[0]), 3), dtype=np.uint8)
        # add text in the center
        cv2.putText(self._black_frame, f"'{config['camera_device']}' Error", (int(config["resolution"].split("x")[0]) // 4, int(config["resolution"].split("x")[1]) // 2), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 5, cv2.LINE_AA)
        self._frame_buffer = []
        self._cur_frame = None
        self._ffmpeg_pid = None
        self.root = self.init_folder_struct()

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
            self.wait_for_camera()

        try:
            # set fps and resolution
            self.cap.set(cv2.CAP_PROP_FPS, config["fps"])
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["resolution"].split("x")[0]))
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["resolution"].split("x")[1]))
        except Exception as e:
            self.logger.error(f"Failed to set video capture properties: {e}")
            sys.exit(1)

    def wait_for_camera(self, delay=2):
        # this is in the event the camera gets unplugged, we wait for it to come back
        self.logger.log(f"Waiting for camera {config['camera_device']} to become available...")
        # for some reason linux likes to change the device number when unplugging and replugging
        # scan if opening config["camera_device"] does not work, start to 0 and dont use 40 its reserved for the virtual cam
        while True:
            if os.path.exists(config["camera_device"]):
                try:
                    test_cap = cv2.VideoCapture(config["camera_device"])
                    if test_cap.isOpened():
                        test_cap.release()
                        self.logger.log(f"Camera {config['camera_device']} is now available")
                        self.cap = cv2.VideoCapture(config["camera_device"])
                        # set fps and resolution
                        self.cap.set(cv2.CAP_PROP_FPS, config["fps"])
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["resolution"].split("x")[0]))
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["resolution"].split("x")[1]))
                        return
                except Exception as e:
                    self.logger.error(f"Error accessing camera {config['camera_device']}: {e}")
            else:
                # iterate through possible video devices
                for i in range(0, 10):
                    device_path = f"/dev/video{i}"
                    if os.path.exists(device_path):
                        try:
                            test_cap = cv2.VideoCapture(device_path)
                            if test_cap.isOpened():
                                test_cap.release()
                                self.logger.log(f"Camera found at {device_path}, updating config")
                                config["camera_device"] = device_path
                                self.cap = cv2.VideoCapture(config["camera_device"])
                                # set fps and resolution
                                self.cap.set(cv2.CAP_PROP_FPS, config["fps"])
                                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["resolution"].split("x")[0]))
                                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["resolution"].split("x")[1]))
                                return
                        except Exception as e:
                            self.logger.error(f"Error accessing camera {device_path}: {e}")
            time.sleep(delay)

    def start(self):
        asyncio.run(self.recv_frame())

    def makeIfNotDir(self, dir_path):
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

    def get_metadata(self):
        mem = psutil.virtual_memory()
        self.metadata["memory_usage"]["total_bytes"] = mem.total
        self.metadata["memory_usage"]["used_bytes"] = mem.used
        self.metadata["memory_usage"]["free_bytes"] = mem.available
        if config["usb_mode"]:
            path = config["usb_path"]
        else:
            path = os.path.expanduser(config["other_path"])
        if os.path.exists(path):
            usage = psutil.disk_usage(path)
            self.metadata["storage_usage"]["total_bytes"] = usage.total
            self.metadata["storage_usage"]["used_bytes"] = usage.used
            self.metadata["storage_usage"]["free_bytes"] = usage.free
        else:
            self.metadata["storage_usage"]["total_bytes"] = 0
            self.metadata["storage_usage"]["used_bytes"] = 0
            self.metadata["storage_usage"]["free_bytes"] = 0
        root = self.root
        self.metadata['root'] = root.rsplit('/', 1)[0]
        return self.metadata
    

    def _getTempPath(self):
        """
        If using USB mode, picasso will first save to a temp folder on the main drive then save onto the USB drive later
        This is done to avoid issues with write speeds on some USB drives which
        could affect video encoding
        """
        if not os.path.exists("/tmp/picasso"):
            os.makedirs("/tmp/picasso", exist_ok=True)
        rand_name = f"temp_{int(time.time())}.avi"
        return os.path.join("/tmp/picasso", rand_name)
    

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
        # iso
        now = datetime.datetime.now().isoformat()
        self.metadata["start_time"] = now
        self.logger.log("Started recording")
        # ffmpeg -f v4l2 -video_size 1280x800 -i /dev/video0 -codec:v h264_omx -b:v 2048k webcam.mkv
        
        next_video_path = self.getNextVideoPath()
        output_path = None
        if config["usb_mode"]:
            self._temp_output_path = self._getTempPath()
            output_path = self._temp_output_path
        else:
            output_path = next_video_path
            self._temp_output_path = None
        proc = subprocess.Popen([
            "ffmpeg",
            "-f", "v4l2",
            "-video_size", config["resolution"],
            "-i", "/dev/video40",
            # "-c:v", "h264_omx",
            "-c:v", config["encoding_format"],
            "-b:v", "2048k",
            output_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) # TODO: add to log files l8r m8
        self._ffmpeg_pid = proc.pid
    
    def _move_thread(self, from_path, to_path):
        shutil.move(from_path, to_path)

    def metadata_track_filemove(self, from_path, to_path):
        # move the file, wait for the to_path file size to be equal to from_path file size
        original_size = os.path.getsize(from_path)
        self.metadata['saving'] = {
            "complete": False,
            "total_bytes": original_size,
            "moved_bytes": 0,
        }
        try:
            # shutil.move(from_path, to_path)
            threading.Thread(target=self._move_thread, args=(from_path, to_path), daemon=True).start()
            self.logger.log(f"Moved recording to {to_path}")
        except Exception as e:
            self.logger.error(f"Failed to move recording to {to_path}: {e}")
            return
        # wait for the to_path file size to be equal to original_size
        start_time = time.time()
        while True:
            if os.path.exists(to_path):
                new_size = os.path.getsize(to_path)
                if new_size == original_size:
                    self.logger.log(f"File move complete: {to_path}")
                    self.metadata['saving']['moved_bytes'] = new_size
                    self.metadata['saving']['complete'] = False
                    break
                self.metadata['saving']['moved_bytes'] = new_size
            # if time.time() - start_time > 30: # this is bad because some drives are slow
            #     self.logger.error(f"File move timeout after 30 seconds: {to_path}")
            #     break

    def stop_recording(self):
        self.metadata["recording"] = False
        self.logger.log("Stopped recording")
        if self._ffmpeg_pid:
            os.kill(self._ffmpeg_pid, signal.SIGTERM)
        if self._temp_output_path and config["usb_mode"]:
            # move the temp file to the usb drive
            next_video_path = self.getNextVideoPath()
            self.metadata_track_filemove(self._temp_output_path, next_video_path)
            self._temp_output_path = None
        

    async def recv_frame(self):
        self.logger.log("Starting frame receiver")
        with pyvirtualcam.Camera(
            width=int(config["resolution"].split("x")[0]),
            height=int(config["resolution"].split("x")[1]),
            fps=config["fps"],
            device=config["virtual_device"]["device"],
            print_fps=False
        ) as vcam:
            while True:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    self.logger.error("Failed to read frame from camera")
                    frame = self._black_frame  # fallback
                    self._failed_frame_count += 1
                    if self._failed_frame_count >= 10:
                        self.wait_for_camera()
                        self._failed_frame_count = 0
                        continue
                else:
                    self._failed_frame_count = 0
                self._cur_frame = frame
                await self.on_frame(frame, vcam)
    async def send_vframe(self, frame: np.ndarray, vcam: pyvirtualcam.Camera):
        vcam.send(frame)
        vcam.sleep_until_next_frame()

    async def on_frame(self, frame: np.ndarray, vcam: pyvirtualcam.Camera):
        if frame is None or frame.size == 0:
            self.logger.error("Received empty frame in on_frame")
            frame = self._black_frame
        frame = cv2.resize(frame, (
            int(config["resolution"].split("x")[0]),
            int(config["resolution"].split("x")[1])
        ))
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

    async def take_picture(self):
        picture_path = self.getNextPicturePath()
        frame = self._cur_frame if self._cur_frame is not None else self._black_frame
        cv2.imwrite(picture_path, frame)
        self.logger.log(f"Saved picture to {picture_path}")
        return (picture_path, os.path.getsize(picture_path)) # size in bytes

app = FastAPI(docs_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
camera = CameraInterface()

def run_camera():
    asyncio.run(camera.recv_frame())
threading.Thread(target=run_camera, daemon=True).start()

# add middleware to check for passcode in header for all routes

#test function to ensure middleware works
@app.middleware("http")
async def test(request: Request, call_next):
    # bypass /stream
    if request.url.path == "/stream":
        response = await call_next(request)
        return response
    # bypass options requests
    if request.method == "OPTIONS":
        response = await call_next(request)
        return response
    header_passcode = request.headers.get("X-Picasso-Passcode")
    if config["secure"]:
        if header_passcode is None or header_passcode == "":
            response = JSONResponse(content={"error": "Unauthorized"}, status_code=401)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            return response
        if request.url.path in ["/start_recording", "/stop_recording", "/take_picture"]:
            if header_passcode != config["passcode"]:
                response = JSONResponse(content={"error": "Unauthorized"}, status_code=401)
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Headers"] = "*"
                return response
    response = await call_next(request)
    return response

@app.get("/stream")
async def stream(req: Request, passcode: str = None):
    if config["secure"] and passcode != config["passcode"]:
        return JSONResponse(content={"error": "Unauthorized"}, status_code=401)

    return StreamingResponse(camera._get_web_stream(req), media_type='multipart/x-mixed-replace; boundary=frame')

@app.get('/start_recording')
async def start_recording():
    camera.start_recording()
    return JSONResponse(content={"status": "recording started", 'metadata': camera.metadata})

@app.get('/stop_recording')
async def stop_recording():
    camera.stop_recording()
    return JSONResponse(content={"status": "recording stopped", 'metadata': camera.metadata})

@app.get('/take_picture')
async def take_picture():
    picture_path, size_bytes = await camera.take_picture()
    return JSONResponse(content={"status": "success", "path": picture_path, "size_bytes": size_bytes}, status_code=200)

@app.get("/metadata")
async def get_metadata(passcode: str = None):
    return JSONResponse(content={"metadata": camera.get_metadata()})