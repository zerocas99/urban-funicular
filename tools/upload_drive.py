import os
import json
import sys
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def main():
    path = sys.argv[1]
    folder_id = os.environ["GDRIVE_FOLDER_ID"]
    sa_json = os.environ["GDRIVE_SA_JSON"]

    filename = os.path.basename(path)
    if os.path.exists("output.name.txt"):
        n = open("output.name.txt", "r", encoding="utf-8").read().strip()
        if n:
            filename = n

    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    media = MediaFileUpload(path, resumable=True)
    meta = {"name": filename, "parents": [folder_id]}
    created = drive.files().create(body=meta, media_body=media, fields="id").execute()
    file_id = created["id"]

    link = drive.files().get(fileId=file_id, fields="webViewLink").execute()["webViewLink"]
    print("\n✅ Uploaded to Google Drive")
    print("File name:", filename)
    print("Link:", link)

if __name__ == "__main__":
    main()
