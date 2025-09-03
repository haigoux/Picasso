from collections import deque
import shutil
import cv2
import os
import sys
import subprocess
import numpy as np
import pyvirtualcam
import time
import psutil
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse, FileResponse
#cors
from fastapi.middleware.cors import CORSMiddleware

from PIL import Image, ImageFont, ImageDraw
# if not "picasso" dir in ~/
VCR_FONT = ImageFont.truetype("vcr.ttf", 35)
PREVIEW_RESOLUTIONS = [(640, 360)]
VCAM_RESOLUTION = (1280, 720)
PREVIEW_RES_INDEX = 0

def makeIfNotDir(path):
    if not os.path.exists(path):
        os.makedirs(path)

# Find if any USB drives are plugged in, and mount them
picasso_dir = None
for path in os.listdir("/media"):
    if "usb" in path.lower():
        picasso_dir = os.path.join("/media", path)
        break

if not picasso_dir:
    print("No USB drive found, using home dir!")
    picasso_dir = os.path.join(os.path.expanduser("~"), "picasso")

makeIfNotDir(picasso_dir)
makeIfNotDir(os.path.join(picasso_dir, "videos"))
makeIfNotDir(os.path.join(picasso_dir, "pictures"))

def getNextVideoPath():
    video_dir = os.path.join(picasso_dir, "videos")
    # picasso/videos/MonthFullNameYYYY/dayNumberHHMMSS.avi
    now = time.localtime()
    month_full_name = time.strftime("%B", now)
    day_number = time.strftime("%d", now)
    time_str = time.strftime("%I_%M_%S_%p", now)
    video_path = os.path.join(video_dir, f"{month_full_name}{now.tm_year}/{day_number}__{time_str}.avi")
    if not os.path.exists(video_path):
        makeIfNotDir(os.path.dirname(video_path))
    return video_path

def getNextPicturePath():
    picture_dir = os.path.join(picasso_dir, "pictures")
    # picasso/pictures/MonthFullNameYYYY/dayNumberHHMMSS.jpg
    now = time.localtime()
    month_full_name = time.strftime("%B", now)
    day_number = time.strftime("%d", now)
    time_str = time.strftime("%I_%M_%S_%p", now)
    picture_path = os.path.join(picture_dir, f"{month_full_name}{now.tm_year}/{day_number}__{time_str}.jpg")
    if not os.path.exists(picture_path):
        makeIfNotDir(os.path.dirname(picture_path))
    return picture_path



# use v4l2-cli to unload the PicassoVirtualCamera if it is present


#  sudo modprobe -r v4l2loopback # Unload the v4l2loopback module just incase
# quit if failed
if subprocess.call(["sudo", "modprobe", "-r", "v4l2loopback"]) != 0:
    print("Failed to unload v4l2loopback module")
    sys.exit(1)
else:
    print("Successfully unloaded v4l2loopback module")

# create the virtual camera so ffmpeg can record from it
subprocess.run(["sudo", "modprobe", "v4l2loopback", "devices=1", "video_nr=40", "card_label=PicassoVirtualCamera", "exclusive_caps=1", "output=1"])

def get_usb_cameras() -> list[str]:
    # returns a list of usb camera /dev paths
    # only use USB cameras dont return the whole list
    cameras = []
    for i in range(10):
        camera_path = f"/dev/video{i}"
        if os.path.exists(camera_path):
            # Check if the camera is a USB camera
            try:
                output = subprocess.check_output(["udevadm", "info", "--query=property", "--name=" + camera_path])
                if b"ID_USB_DRIVER" in output:
                    cameras.append(camera_path)
            except subprocess.CalledProcessError:
                pass
    return cameras

camera_path = get_usb_cameras()[0] if get_usb_cameras() else None

class WindowInterface:
    def __init__(self, camera_path: str | None, show_window: bool=False, web_server: bool=False, web_port: int=8080):
        self.camera_path = camera_path
        self.output_frame = None
        self.rescaled_frame_resolution = (800, 600)
        self.show_window = show_window
        self.rescaled_frame = None
        self.window_name = "Camera Feed"
        self.window_resolution = (1280, 720)
        self.capture = cv2.VideoCapture(self.camera_path) if self.camera_path else None
        self.uptime = time.time()
        self._pic_label_time = 0
        self._pic_show_error = False
        self._pic_show_saved = False
        self._stat = False
        self._file_move_start_time = 0
        self._file_move_target_path = ""
        self._file_moved_percentage = 0.0
        self._moving_file = False
        self.storage_remaining = round(os.statvfs(os.path.expanduser("~")).f_bavail * os.statvfs(os.path.expanduser("~")).f_frsize / (1024**3), 2)  # in GB
        # video / picture vars
        self.recording = False
        self.next_video_path = getNextVideoPath()
        self.next_picture_path = getNextPicturePath()
        self.recording_time = "--:--:--"
        self._recording_start_time = time.time()
        # set FPS to 60
        # set resolution to 1920x1080
        if self.capture:
            self.capture.set(cv2.CAP_PROP_FPS, 60)
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, VCAM_RESOLUTION[0])
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, VCAM_RESOLUTION[1])
            self.window_resolution = (int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        
    async def start_vframe_stream(self):
        task1 = asyncio.create_task(self.send_virtual_frame())
        task2 = asyncio.create_task(self.show())
        task3 = asyncio.create_task(self.update_loop())
        await asyncio.gather(task1, task2, task3)

    async def shutil_progress_track(self, from_path, to_path):
        total_size = os.path.getsize(from_path)
        # reset self vars
        self._file_move_start_time = time.time()
        self._file_move_target_path = to_path
        self._file_moved_percentage = 0.0
        self._moving_file = True
        buffer_size = 256 * 4096  # 2MB
        chunks_since_yield = 0
        with open(from_path, 'rb') as fsrc, open(to_path, 'wb') as fdst:
            copied = 0
            while True:
                buf = fsrc.read(buffer_size)
                if not buf:
                    print("File move complete")
                    break
                fdst.write(buf)
                copied += len(buf)
                self._file_moved_percentage = copied / total_size * 100
                chunks_since_yield += 1
                print(f"Moving file... {self._file_moved_percentage:.2f}%")
                if chunks_since_yield >= 1:  # yield every 2MB
                    await asyncio.sleep(0)
                    chunks_since_yield = 0
        self._moving_file = False

    def vcam_error_frame(self) -> np.ndarray:
        # Create a red error frame
        return np.full((VCAM_RESOLUTION[1], VCAM_RESOLUTION[0], 3), (255, 0, 0), np.uint8)  # BGR

    def update_next_paths(self):
        self.next_video_path = getNextVideoPath()
        self.next_picture_path = getNextPicturePath()

    def update_storage_info(self):
        self.storage_remaining = {
            'used': round(os.statvfs(os.path.expanduser("~")).f_bavail * os.statvfs(os.path.expanduser("~")).f_frsize / (1024**3), 2),  # in GB
            'total': round(os.statvfs(os.path.expanduser("~")).f_blocks * os.statvfs(os.path.expanduser("~")).f_frsize / (1024**3), 2)  # in GB
        }
        self.memory_usage = {
            'used': round(psutil.virtual_memory().used / (1024**2), 2),  # in MB
            'total': round(psutil.virtual_memory().total / (1024**2), 2)  # in MB
        }

    async def send_virtual_frame(self):
        with pyvirtualcam.Camera(width=VCAM_RESOLUTION[0], height=VCAM_RESOLUTION[1], fps=60, device='/dev/video40') as cam:
            print(f'Using virtual camera: {cam.device}')
            while True:
                frame = self.output_frame if self.output_frame is not None else self.vcam_error_frame()
                # convert to BGR
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                # if frame is not VCAM res, resize
                if frame.shape[1] != VCAM_RESOLUTION[0] or frame.shape[0] != VCAM_RESOLUTION[1]:
                    frame = cv2.resize(frame, (VCAM_RESOLUTION[0], VCAM_RESOLUTION[1]))
                cam.send(frame)
                cam.sleep_until_next_frame()
                await asyncio.sleep(0)  # yield to event loop

    async def update_loop(self):
        while True:
            self.update_storage_info()
            await asyncio.sleep(1.0)

    async def start_recording(self):
        self.update_next_paths()
        temp_video_path = os.path.expanduser("~/.picasso_temp.avi")
        if os.path.exists(temp_video_path):
            # remove that thing
            os.remove(temp_video_path)
        # run ffmpeg -f video4linux2 -framerate 60 -video_size 1920x1080 -i /dev/video10 -f alsa -i hw:1 {self.next_video_path}
        subprocess.Popen([
            "ffmpeg",
            "-f", "v4l2",
            "-video_size", "1280x720",
            "-i", "/dev/video40",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "13",
            "-r", "60",
            temp_video_path
        ])
        self.recording = True
        self._recording_start_time = time.time()
        print(f"Started recording: {temp_video_path}")
        while self.recording:
            await asyncio.sleep(1.0)
            self.recording_time = time.strftime("%H:%M:%S", time.gmtime(time.time() - self._recording_start_time)) if self.recording else "--:--:--"
        # stop ffmpeg process
        subprocess.Popen(["pkill", "-f", "ffmpeg"])
        print(f"Stopped recording: {temp_video_path}")
        # move to USB drive
        usb_drive_path = "/media/usb1"

        if os.path.exists(usb_drive_path):
            print(f"Moving temp recording to: {self.next_video_path}")
            await self.shutil_progress_track(temp_video_path, self.next_video_path)
        else:
            print(f"USB drive not found: {usb_drive_path}")

    def stop_recording(self):
        self.recording = False

    def text(self, position, text, color, shadow: bool=False, size: int=1):
        # if shadow:
        #     cv2.putText(self.rescaled_frame, text, (position[0]+1, position[1]+1), cv2.FONT_HERSHEY_SIMPLEX, size, (0, 0, 0), 5)
        # cv2.putText(self.rescaled_frame, text, position, cv2.FONT_HERSHEY_SIMPLEX, size, color, 3)
        # use PIL for text rendering instead
        VCR_FONT = ImageFont.truetype("vcr.ttf", 35 * size)
        if self.rescaled_frame is not None:
            pil_img = Image.fromarray(self.rescaled_frame)
            draw = ImageDraw.Draw(pil_img)
            if shadow:
                draw.text((position[0]+1, position[1]-24), text, font=VCR_FONT, fill=(0, 0, 0))
            draw.text((position[0], position[1] - 25), text, font=VCR_FONT, fill=color)
            self.rescaled_frame = np.array(pil_img)

    async def take_picture(self):
        self.update_next_paths()
        if self.output_frame is not None:
            # convert to BGR
            converted = cv2.cvtColor(self.output_frame, cv2.COLOR_RGB2BGR)
            pil_img = Image.fromarray(converted)
            path = self.next_picture_path
            pil_img.save(path)
            print(f"Saved picture: {path}")
            self._pic_label_time = time.time()
            self._pic_show_saved = True
        else:
            self._pic_label_time = time.time()
            self._pic_show_error = True



    def welcome_label(self):
        center = ((self.rescaled_frame_resolution[0] // 2) -80, self.rescaled_frame_resolution[1] // 2)
        self.text(center, "PICASSO", (255, 255, 255), True, 1)

    def recording_label(self, position, radius=5):
        if self.rescaled_frame is not None:
            cv2.circle(self.rescaled_frame, position, radius, (0, 0, 255), -1)
            cv2.circle(self.rescaled_frame, position, radius+2, (0, 0, 0), 2)
            self.text((position[0] + radius + 12, (position[1] + radius // 2) + 4), "RECORDING", (255, 255, 255), True, 1)

    def recording_time_label(self, position):
        if self.rescaled_frame is not None:
            self.recording_time = time.strftime("%H:%M:%S", time.gmtime(time.time() - self._recording_start_time)) if self.recording else "--:--:--"
            self.text((position[0], position[1]), self.recording_time, (255, 255, 255), True, 1)

    def stat_overlay(self):
        # draw resolution, storage remaining, memory usage
        top_offset = 200
        gap = 40
        if self.rescaled_frame is not None:
            self.text((30, top_offset), f"{self.rescaled_frame.shape[1]}x{self.rescaled_frame.shape[0]}", (255, 255, 255), True, 1)
            self.text((30, top_offset + gap), f"{self.storage_remaining['used']} GB / {self.storage_remaining['total']} GB", (255, 255, 255), True, 1)
            self.text((30, top_offset + gap * 2), f"{self.memory_usage['used']} MB / {self.memory_usage['total']} MB", (255, 255, 255), True, 1)

    def draw_interface(self):
        if self.rescaled_frame is not None:
            if time.time() - self.uptime < 5:
                self.welcome_label()
            if self.recording:
                self.recording_label((30, 30), radius=10)
                self.recording_time_label((30, 80))
            if self._pic_show_saved and time.time() - self._pic_label_time < 3:
                self.text((30, 120), "PICTURE SAVED", (255, 255, 255), True, 1)
            if self._pic_show_error and time.time() - self._pic_label_time < 3:
                self.text((30, 120), "PICTURE SAVE ERROR", (255, 0, 0), True, 1)
            if self._stat:
                self.stat_overlay()
            if self._moving_file:
                self.text((30, 30), f"SAVING, DO NOT UNPLUG USB DRIVE", (0, 0, 255), True, 0.7)
                self.text((30, 60), f"PROGRESS: {self._file_moved_percentage:.2f}%", (255, 255, 255), True, 0.7)

    def set_resolution(self, index):
        global PREVIEW_RES_INDEX
        PREVIEW_RES_INDEX = index
        self.rescaled_frame_resolution = PREVIEW_RESOLUTIONS[PREVIEW_RES_INDEX]

    def inc_prev_res(self):
        global PREVIEW_RES_INDEX
        PREVIEW_RES_INDEX = (PREVIEW_RES_INDEX + 1) % len(PREVIEW_RESOLUTIONS)
        self.set_resolution(PREVIEW_RES_INDEX)

    def dec_prev_res(self):
        global PREVIEW_RES_INDEX
        PREVIEW_RES_INDEX = (PREVIEW_RES_INDEX - 1) % len(PREVIEW_RESOLUTIONS)
        self.set_resolution(PREVIEW_RES_INDEX)

    async def show(self):
        global PREVIEW_RES_INDEX
        self.set_resolution(PREVIEW_RES_INDEX)
        # gradient black to white
        # load gradient.png
        gradient_frame = cv2.imread("gradient.png", cv2.IMREAD_COLOR)
        if gradient_frame is None:
            print("Failed to load gradient image.")
            return
        gradient_frame = cv2.resize(gradient_frame, self.rescaled_frame_resolution)
        if not self.capture:
            print("No camera found.")
            return

        while True:

            if self._moving_file:
                frame = gradient_frame
            else:
                ret, frame = self.capture.read()
                if not ret:
                    print("Failed to grab frame.")
                    break

            self.output_frame = frame
            # rescaled frame
            self.rescaled_frame = cv2.resize(self.output_frame, self.rescaled_frame_resolution)

            self.draw_interface()
            if self.show_window:
                cv2.namedWindow(self.window_name, cv2.WINDOW_GUI_NORMAL)
                cv2.imshow(self.window_name, self.rescaled_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("r"):
                if not self.recording:
                    asyncio.create_task(self.start_recording())
                else:
                    self.stop_recording()
            elif key == ord("q"):
                break
            elif key == ord("p"):
                asyncio.create_task(self.take_picture())
            elif key == ord("s"):
                self._stat = not self._stat
            elif key == ord("m"):
                PREVIEW_RES_INDEX = (PREVIEW_RES_INDEX + 1) % len(PREVIEW_RESOLUTIONS)
                self.set_resolution(PREVIEW_RES_INDEX)
            elif key == ord("n"):
                PREVIEW_RES_INDEX = (PREVIEW_RES_INDEX - 1) % len(PREVIEW_RESOLUTIONS)
                self.set_resolution(PREVIEW_RES_INDEX)
            await asyncio.sleep(0)  # yield to event loop

    def cleanup(self):
        if self.capture:
            self.capture.release()
        cv2.destroyAllWindows()


window = WindowInterface(camera_path, show_window=False)
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Start the frame stream in FastAPI's startup event
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(window.start_vframe_stream())

async def gen_frames(request: Request):
    while await request.is_disconnected() is False:
        _, buffer = cv2.imencode('.jpg', window.rescaled_frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.get("/stream")
async def stream_video(request: Request):
    return StreamingResponse(gen_frames(request), media_type='multipart/x-mixed-replace; boundary=frame')

@app.get("/start_recording")
async def start_recording():
    asyncio.create_task(window.start_recording())
    # route to /stream
    return RedirectResponse(url="/")

@app.get("/stop_recording")
async def stop_recording():
    window.stop_recording()
    return RedirectResponse(url="/")

@app.get("/save_image")
async def save_image():
    asyncio.create_task(window.take_picture())
    return RedirectResponse(url="/")

@app.get("/increase_preview_resolution")
async def increase_preview_resolution():
    window.inc_prev_res()
    return RedirectResponse(url="/")

@app.get("/decrease_preview_resolution")
async def decrease_preview_resolution():
    window.dec_prev_res()
    return RedirectResponse(url="/")

@app.get("/")
async def root():
    return FileResponse("web/index.html")

@app.get("/debug_toggle")
async def debug_toggle():
    window._stat = not window._stat
    return RedirectResponse(url="/")

@app.get("/static/{path:path}")
async def serve_static_files(path: str):
    return FileResponse(f"web/{path}")

@app.get("/is_recording")
async def is_recording():
    return {"is_recording": window.recording}