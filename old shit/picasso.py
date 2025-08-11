import cv2
import sys, subprocess, os, json, time, random, shutil
import numpy as np
# surpress OpenCV warnings
cv2.setLogLevel(0)

# First, get the camera devices
def get_camera_devices():
    video_devices = []
    # Use OpenCV to get the list of camera devices
    for i in range(10):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            video_devices.append(i)
            cap.release()
    return video_devices

VIDEO_DEVICES = get_camera_devices()


def get_video_device_names():
    output = subprocess.check_output(['v4l2-ctl', '--list-devices'], text=True)
    lines = output.splitlines()

    names = []
    for line in lines:
        if line and not line.startswith('\t') and not line.startswith(' '):
            # Only non-indented lines are device names
            names.append(line.strip())

    return names

print("Available camera devices:", len(VIDEO_DEVICES))
# select the first available camera device
if len(VIDEO_DEVICES) > 0:
    CAMERA_DEVICE = VIDEO_DEVICES[0]
else:
    print("Waiting for camera device...")
    while len(VIDEO_DEVICES) == 0:
        time.sleep(1)
        VIDEO_DEVICES = get_camera_devices()
    CAMERA_DEVICE = VIDEO_DEVICES[0]

# Set the camera device to use
os.environ['CAMERA_DEVICE'] = str(CAMERA_DEVICE)
print("Using camera device:", CAMERA_DEVICE)



def get_next_filename():
    folder = os.path.expanduser(f'~/picasso/video/{time.strftime("%B-%Y")}')
    if not os.path.exists(folder):
        os.makedirs(folder)

    date_str = time.strftime("%B%d_%Y")
    files = os.listdir(folder)
    count = 0
    for file in files:
        if file.startswith(date_str):
            try:
                num = int(file.split('_')[-1].split('.')[0])
                count = max(count, num + 1)
            except ValueError:
                continue
    return f"{folder}/{date_str}_{count}.mp4"

def get_next_picture_filename():
    folder = os.path.expanduser(f'~/picasso/pictures/{time.strftime("%B-%Y")}')
    if not os.path.exists(folder):
        os.makedirs(folder)

    date_str = time.strftime("%B%d_%Y")
    files = os.listdir(folder)
    count = 0
    for file in files:
        if file.startswith(date_str):
            try:
                num = int(file.split('_')[-1].split('.')[0])
                count = max(count, num + 1)
            except ValueError:
                continue
    return f"{folder}/{date_str}_{count}.jpg"

def resolution_of_device(device):
    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        raise ValueError(f"Could not open camera device {device}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return [width, height]

def glitch_video_frame(frame, intensity=0.5):
    """
    Apply a glitch/corruption effect to a frame.
    
    Parameters:
        frame (ndarray): Input frame (BGR).
        intensity (float): Corruption intensity (0 to 1).
    
    Returns:
        ndarray: Corrupted frame.
    """
    corrupted = frame.copy()
    h, w, _ = corrupted.shape

    # 1. Shift color channels randomly
    for c in range(3):  # B, G, R
        shift = random.randint(-5, 5)
        corrupted[..., c] = np.roll(corrupted[..., c], shift, axis=1)

    # 2. Horizontal tear (line offset)  
    for _ in range(int(20 * intensity)):
        y = random.randint(0, h - 1)
        offset = random.randint(-20, 20)
        corrupted[y] = np.roll(corrupted[y], offset, axis=0)

    # 3. Add random noise
    noise = np.random.randint(0, 50, (h, w, 3), dtype=np.uint8)
    corrupted = cv2.add(corrupted, noise)

    # 4. Random block shifting
    for _ in range(int(5 * intensity)):
        x = random.randint(0, w - 20)
        y = random.randint(0, h - 20)
        block_w = random.randint(10, 40)
        block_h = random.randint(10, 40)
        dx = random.randint(-20, 20)
        dy = random.randint(-20, 20)

        block = corrupted[y:y+block_h, x:x+block_w]
        nx = np.clip(x + dx, 0, w - block_w)
        ny = np.clip(y + dy, 0, h - block_h)
        corrupted[ny:ny+block_h, nx:nx+block_w] = block

    return corrupted
FPS = 30
menu_open = False
recording = False
stats_overlay = False
fourcc = cv2.VideoWriter.fourcc(*'mp4v')
out = None
record_path = os.path.expanduser('~/picasso/video')
if not os.path.exists(record_path):
    os.makedirs(record_path)

icon_timer = time.time()
icon_on = False
save_png = cv2.imread(os.path.realpath('./save.png'))
corner_text = 'Started.'
# calculated frame rate
# start video capture and display window
resolution = resolution_of_device(CAMERA_DEVICE)
cv2.namedWindow('Picasso', cv2.WINDOW_GUI_NORMAL)
cv2.resizeWindow('Picasso', resolution[0], resolution[1])
cap = cv2.VideoCapture(CAMERA_DEVICE)
if not cap.isOpened():
    print("Error: Could not open camera device.")
    sys.exit(1)
cap.set(cv2.CAP_PROP_FPS, FPS)
frame_count = 0
glitch = False
recording_start_time = None

while True:

    if not cap:
        # show the blank frame
        frame = cv2.imread(os.path.realpath('./bg.png'))
        if frame is None:
            print("Error: Could not load background image.")
            break
        frame = cv2.resize(frame, (resolution[0], resolution[1]))
        # center of screen
        cv2.putText(frame, "No camera selected/connected.", 
                    (frame.shape[1] // 2 - 100, frame.shape[0] // 2), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
    else:
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read frame from camera.")
            break
    og_frame = frame.copy()
        # resize the frame to the resolution of the camera
    if glitch:
        try:
            frame = glitch_video_frame(frame)
        except Exception as e:
            print(f"Error applying glitch effect: {e}")
    # black text shaodwe
    cv2.putText(frame, f'r: { "start recording" if not recording else "stop recording"} | p: save picture | s: view stats | < >: device | g: glitch',
                (11, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
    # Text overlay top left: m to menu, q to quit, different font
    cv2.putText(frame, f'r: { "start recording" if not recording else "stop recording"} | p: save picture | s: view stats | < >: device | g: glitch', 
                (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)


    
    if recording:
        # Write the frame to the video file
        out.write(og_frame)
        cv2.putText(frame, "Recording...", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        icon_on = True
        icon_timer = time.time()
        frame_count += 1


    if stats_overlay:
        # Display some stats overlay
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))    
        stats_text = f"fps: {fps:.2f} | output res: {width}x{height} | storage: {shutil.disk_usage('/').free / (1024**3):.2f} / {shutil.disk_usage('/').total / (1024**3):.2f} gb"
        if recording:
            stats_text += f" | recording time: {time.time() - recording_start_time:.2f} seconds"
        for line in stats_text.split('|'):
            cv2.putText(frame, line.strip(), (10, 50 + 30 * stats_text.split('|').index(line)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    if icon_on and time.time() - icon_timer < 3:
        # Display the save icon for 3 seconds
        icon_height, icon_width = save_png.shape[:2]
        x_offset = frame.shape[1] - icon_width - 10
        y_offset = frame.shape[0] - icon_height - 10
        frame[y_offset:y_offset + icon_height, x_offset:x_offset + icon_width] = save_png

    # Wait for 1 ms and check if the user pressed 'q' to quit
    match = cv2.waitKey((1000 // FPS)) & 0xFF
    if match == ord('<') and not recording:
        if len(VIDEO_DEVICES) > 0:
            # close the current camera
            if cap is not None:
                cap.release()
            CAMERA_DEVICE = VIDEO_DEVICES[(VIDEO_DEVICES.index(CAMERA_DEVICE) - 1) % len(VIDEO_DEVICES)]
            resolution = resolution_of_device(CAMERA_DEVICE)

            cap.release()
            cap = cv2.VideoCapture(CAMERA_DEVICE)
            print(f"Switched to camera device: {CAMERA_DEVICE}")
    elif match == ord('>') and not recording:
        if len(VIDEO_DEVICES) > 0:
            # close the current camera
            if cap is not None:
                cap.release()
            CAMERA_DEVICE = VIDEO_DEVICES[(VIDEO_DEVICES.index(CAMERA_DEVICE) + 1) % len(VIDEO_DEVICES)]
            cap.release()
            resolution = resolution_of_device(CAMERA_DEVICE)
            cap = cv2.VideoCapture(CAMERA_DEVICE)
            print(f"Switched to camera device: {CAMERA_DEVICE}")
    if match == ord('q'):
        print("Quitting...")
        break
    elif match == ord('m'):
        # Toggle the menu state
        menu_open = not menu_open
        print("Menu toggled")
    elif match == ord('r'):
        # Toggle recording state
        if recording:
            # If starting recording, create a new video file
            if out.isOpened():
                out.release()
        else:
            out = cv2.VideoWriter(get_next_filename(), fourcc, FPS, (640, 480))
            frame_count = 0
            recording_start_time = time.time()
        recording = not recording
        corner_text = f'recording to {get_next_filename().rsplit("video/", 1)[-1]}' if recording else 'Stopped recording.'
        print("Recording started" if recording else "Recording stopped")
    elif match == ord('p'):
        # Save a picture
        picture_filename = get_next_picture_filename()
        cv2.imwrite(picture_filename, og_frame)
        print(f"Picture saved as {picture_filename}")
        icon_on = True
        icon_timer = time.time()
        corner_text = f'Saved picture as {picture_filename.rsplit("pictures/", 1)[-1]}'
    elif match == ord('c'):
        # Close the camera
        cap.release()
        cap = None
    elif match == ord('g'):
        # Toggle glitch effect
        glitch = not glitch
        print("Glitch effect toggled")
    elif match == ord('s'):
        # Toggle stats overlay
        stats_overlay = not stats_overlay
        if stats_overlay:
            corner_text = 'Stats overlay enabled.'
        else:
            corner_text = 'Stats overlay disabled.'
        print("Stats overlay toggled")


    frame = cv2.resize(frame, (resolution[0], resolution[1]))
    cv2.putText(frame, corner_text, (10, frame.shape[0] - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    # Show the frame in the window
    cv2.imshow('Picasso', frame)

# Release the camera and close the window
cap.release()
cv2.destroyAllWindows()