import fastapi
import os
import sys
import subprocess

app = fastapi.FastAPI()

@app.get("/")
async def root():
    return {"message": "Welcome to the Picasso API!"}

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