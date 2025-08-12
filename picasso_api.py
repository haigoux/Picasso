import fastapi
import os
import sys
import subprocess
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
#cors
from fastapi.middleware.cors import CORSMiddleware
import cv2
import time

# if not "picasso" dir in ~/
def makeIfNotDir(path):
    if not os.path.exists(path):
        os.makedirs(path)

makeIfNotDir(os.path.join(os.path.expanduser("~"), "picasso"))
makeIfNotDir(os.path.join(os.path.expanduser("~"), "picasso", "videos"))
makeIfNotDir(os.path.join(os.path.expanduser("~"), "picasso", "pictures"))

def getNextVideoPath():
    video_dir = os.path.join(os.path.expanduser("~"), "picasso", "videos")
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
    picture_dir = os.path.join(os.path.expanduser("~"), "picasso", "pictures")
    # picasso/pictures/MonthFullNameYYYY/dayNumberHHMMSS.jpg
    now = time.localtime()
    month_full_name = time.strftime("%B", now)
    day_number = time.strftime("%d", now)
    time_str = time.strftime("%I_%M_%S_%p", now)
    picture_path = os.path.join(picture_dir, f"{month_full_name}{now.tm_year}/{day_number}__{time_str}.jpg")
    if not os.path.exists(picture_path):
        makeIfNotDir(os.path.dirname(picture_path))
    return picture_path

cap = cv2.VideoCapture(0)
fps = 30 # target fps for output video
actual_camera_fps = 30  # will be detected from camera
recording = False
video_writer = None
recording_time_start = None
frame_buffer = []
last_frame_time = None
frame_interval = 1.0 / fps  # target time between frames

app = fastapi.FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    # return {"camera_active": cap.isOpened(), 'camera_recording': recording, 'fps': fps}
    return JSONResponse(status_code=200, content={"camera_active": cap.isOpened(), 'camera_recording': recording, 'target_fps': fps, 'camera_fps': actual_camera_fps})

@app.get('/reload-camera')
async def reload_camera():
    global cap, fps, actual_camera_fps, frame_interval
    if cap.isOpened():
        cap.release()
    cap = cv2.VideoCapture(0)
    actual_camera_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = 1.0 / fps  # recalculate frame interval
    if not cap.isOpened():
        return JSONResponse(status_code=500, content={"error": "Failed to open camera"})
    return JSONResponse(status_code=200, content={"message": "Camera reloaded successfully", "camera_fps": actual_camera_fps, "target_fps": fps})

@app.get("/run-script/{script_name}")
async def run_script(script_name: str):
    script_path = os.path.join(os.getcwd(), script_name)
    if not os.path.exists(script_path):
        return {"error": "Script not found."}
    
    try:
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        return {"error": str(e)}

def should_write_frame():
    """Determines if current frame should be written based on timing"""
    global last_frame_time, frame_interval
    current_time = time.time()
    
    if last_frame_time is None:
        last_frame_time = current_time
        return True
    
    time_since_last = current_time - last_frame_time
    
    if time_since_last >= frame_interval:
        last_frame_time = current_time
        return True
    
    return False

def stabilize_frame_rate(frame):
    """Add frame to buffer and return frame to write if timing is right"""
    global frame_buffer
    
    frame_buffer.append(frame.copy())
    
    # Keep buffer size reasonable
    if len(frame_buffer) > 10:
        frame_buffer.pop(0)
    
    if should_write_frame():
        if frame_buffer:
            return frame_buffer[-1]  # Return most recent frame
    
    return None
    
async def gen_frames(request: fastapi.Request):
    global video_writer
    while await request.is_disconnected() is False:
        if not cap.isOpened():
            print("Failed to open camera")
            break
        ret, frame = cap.read()
        if not ret:
            break
            
        # For streaming, always show the latest frame
        _, buffer = cv2.imencode('.jpg', frame)
        
        # For recording, use frame rate stabilization
        if recording and video_writer is not None:
            stabilized_frame = stabilize_frame_rate(frame)
            if stabilized_frame is not None:
                video_writer.write(stabilized_frame)

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.get("/start-recording")
async def start_recording():
    global recording, video_writer, cap, fps, recording_time_start, last_frame_time, frame_buffer
    if recording:
        return JSONResponse(status_code=400, content={"error": "Recording already in progress"})
    
    # Reset frame timing variables
    last_frame_time = None
    frame_buffer = []
    
    recording = True
    recording_time_start = time.monotonic()
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    vid_path = getNextVideoPath()
    video_writer = cv2.VideoWriter(vid_path, fourcc, fps, (int(cap.get(3)), int(cap.get(4))))

    return JSONResponse(status_code=200, content={"message": "Recording started", "video_path": vid_path, "target_fps": fps, "camera_fps": actual_camera_fps})

@app.get("/stop-recording")
async def stop_recording():
    global recording, video_writer, frame_buffer, last_frame_time
    if not recording:
        return JSONResponse(status_code=400, content={"error": "No recording in progress"})
    
    recording = False
    video_writer.release()
    video_writer = None
    
    # Clear frame timing variables
    frame_buffer = []
    last_frame_time = None

    return JSONResponse(status_code=200, content={"message": "Recording stopped", "duration": time.monotonic() - recording_time_start})

@app.get("/stream")
async def stream_video(request: fastapi.Request):
    return StreamingResponse(gen_frames(request), media_type='multipart/x-mixed-replace; boundary=frame')

def get_thumbnail(video_path: str):
    if not os.path.exists(video_path):
        return None
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    
    # Get the frame at 1 second
    cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        return None
    
    thumbnail_path = video_path.replace('.avi', '_thumbnail.jpg')
    cv2.imwrite(thumbnail_path, frame)
    
    return thumbnail_path

# ?path=video_path
@app.get('/video-thumbnail')
async def video_thumbnail(path: str):
    if not path:
        return JSONResponse(status_code=400, content={"error": "No video path provided"})
    
    thumbnail_path = get_thumbnail(path)
    if not thumbnail_path:
        return JSONResponse(status_code=404, content={"error": "Thumbnail could not be created"})
    
    return FileResponse(thumbnail_path, media_type='image/jpeg')

@app.get("/picture-thumbnail")
async def picture_thumbnail(path: str):
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "Picture file not found"})
    
    # Create a thumbnail by resizing the image to 200x200
    img = cv2.imread(path)
    if img is None:
        return JSONResponse(status_code=500, content={"error": "Failed to read image"})
    
    print(path)
    if os.path.exists(path.replace('.jpg', '_thumbnail.jpg')):
        print("Thumbnail already exists, returning existing thumbnail")
        return FileResponse(path.replace('.jpg', '_thumbnail.jpg'), media_type='image/jpeg')

    thumbnail = cv2.resize(img, (200, 200))
    thumbnail_path = path.replace('.jpg', '_thumbnail.jpg')
    cv2.imwrite(thumbnail_path, thumbnail)
    
    return FileResponse(thumbnail_path, media_type='image/jpeg')

@app.get("/video-files")
async def get_video_files():
    video_dir = os.path.join(os.path.expanduser("~"), "picasso", "videos")
    if not os.path.exists(video_dir):
        return JSONResponse(status_code=404, content={"error": "No videos found"})
    
    video_files = []
    # recursively find all .avi files in the video directory
    for root, dirs, files in os.walk(video_dir):
        for file in files:
            if file.endswith('.avi'):
                video_files.append(os.path.join(root, file))
    return JSONResponse(status_code=200, content={"video_files": video_files})

@app.get("/picture-files")
async def get_picture_files():
    picture_dir = os.path.join(os.path.expanduser("~"), "picasso", "pictures")
    if not os.path.exists(picture_dir):
        return JSONResponse(status_code=404, content={"error": "No pictures found"})
    
    picture_files = []
    # recursively find all .jpg files in the picture directory
    for root, dirs, files in os.walk(picture_dir):
        for file in files:
            if file.endswith('.jpg'):
                picture_files.append(os.path.join(root, file))
    # remove thumbnails from the list
    picture_files = [file for file in picture_files if not file.endswith('_thumbnail.jpg')]
    return JSONResponse(status_code=200, content={"picture_files": picture_files})

@app.get("/update-fps")
async def update_fps(new_fps: int):
    global fps, frame_interval
    if new_fps <= 0:
        return JSONResponse(status_code=400, content={"error": "FPS must be a positive integer"})
    if new_fps > 60:
        return JSONResponse(status_code=400, content={"error": "FPS cannot be greater than 60"})
    
    fps = new_fps
    frame_interval = 1.0 / fps  # update frame interval
    return JSONResponse(status_code=200, content={"message": "FPS updated successfully", "new_target_fps": fps, "camera_fps": actual_camera_fps})

@app.get("/camera-info")
async def get_camera_info():
    global cap, fps, actual_camera_fps
    if not cap.isOpened():
        return JSONResponse(status_code=500, content={"error": "Camera not opened"})
    
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    detected_fps = cap.get(cv2.CAP_PROP_FPS)
    
    return JSONResponse(status_code=200, content={
        "camera_fps": detected_fps,
        "target_fps": fps,
        "resolution": f"{width}x{height}",
        "frame_interval": frame_interval
    })

@app.get("/take-picture")
async def take_picture():
    global cap, recording, video_writer
    if not cap.isOpened():
        return JSONResponse(status_code=500, content={"error": "Camera not opened"})
    
    ret, frame = cap.read()
    if not ret:
        return JSONResponse(status_code=500, content={"error": "Failed to capture image"})
    
    picture_path = getNextPicturePath()
    cv2.imwrite(picture_path, frame)
    
    # If recording, use frame rate stabilization for the video
    if recording and video_writer is not None:
        stabilized_frame = stabilize_frame_rate(frame)
        if stabilized_frame is not None:
            video_writer.write(stabilized_frame)
    
    return JSONResponse(status_code=200, content={"message": "Picture taken", "picture_path": picture_path})

@app.get("/download-video")
async def download_video(path: str):
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "Video file not found"})
    
    return FileResponse(path, media_type='video/avi', filename=os.path.basename(path))

@app.get("/download-picture")
async def download_picture(path: str):
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "Picture file not found"})
    
    return FileResponse(path, media_type='image/jpeg', filename=os.path.basename(path))

@app.get("/delete-video")
async def delete_video(path: str):
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "Video file not found"})
    
    os.remove(path)
    # remove thumbnail if it exists
    thumbnail_path = path.replace('.avi', '_thumbnail.jpg')
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)
    return JSONResponse(status_code=200, content={"message": "Video deleted successfully"})

@app.get("/delete-picture")
async def delete_picture(path: str):
    if not path or not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "Picture file not found"})
    
    os.remove(path)
    # remove thumbnail if it exists
    thumbnail_path = path.replace('.jpg', '_thumbnail.jpg')
    if os.path.exists(thumbnail_path):
        os.remove(thumbnail_path)
    return JSONResponse(status_code=200, content={"message": "Picture deleted successfully"})