#!/usr/bin/env python3
# Generates a Fernet key and adds/updates it in a local .env file.
# Preserves all other lines and works line-by-line. Waits for a key press.

from pathlib import Path
from cryptography.fernet import Fernet
import tempfile
import shutil

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = BASE_DIR / ".env"
BKP_FILE = BASE_DIR / ".env.bkp"
KEY_NAME = "FERNET_KEY"

def main():
    # Generate a new Fernet key
    key = Fernet.generate_key().decode("utf-8")
    print(f"Generated Fernet key:\n{key}")

    print("\nEditing .env file...")

    updated = False
    # Use a temporary file
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as temp_file:
        if ENV_FILE.exists():
            with ENV_FILE.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith(f"{KEY_NAME}=") and not updated:
                        temp_file.write(f"{KEY_NAME}={key}\n")
                        updated = True
                    else:
                        temp_file.write(line)

        # If the file didn't exist or key was not updated, append it
        if not updated:
            temp_file.write(f"{KEY_NAME}={key}\n")

    # Backup the original file
    shutil.move(ENV_FILE, BKP_FILE)
    print(f"Backed up {ENV_FILE} to {BKP_FILE}.")

    # Replace the original file with the temp file
    shutil.move(temp_file.name, ENV_FILE)
    print(f"Updated {ENV_FILE} with {KEY_NAME}.")

if __name__ == "__main__":
    main()
    input("\nPress Enter to exit…")
