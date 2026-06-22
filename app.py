import streamlit as st
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

st.title("生徒向け 倒立見本動画アップローダー")
st.write("動画ファイルをGoogleドライブへアップロードし、スプレッドシートのマスターデータと同期します。")

# 生徒を特定するための入力欄（スプレッドシートの検索キーになります）
student_id = st.text_input("生徒番号（またはクラス名など）を入力してください")
uploaded_file = st.file_uploader("生徒に見せる動画（MP4形式）を選択してください", type=["mp4"])

if uploaded_file is not None and student_id != "":
    if st.button("送信を開始"):
        
        temp_file_path = f"temp_{uploaded_file.name}"
        with open(temp_file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        progress_bar = st.progress(0)
        status_text = st.empty()
        status_text.text("Google Drive API 認証中...")

        try:
            # 1. 認証設定
            SCOPES = ['https://www.googleapis.com/auth/drive']
            service_account_info = st.secrets["gcp_service_account"]
            creds = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=SCOPES)
            drive_service = build('drive', 'v3', credentials=creds)

            # 2. 一時保存フォルダIDとGASのURLを取得
            TEMP_FOLDER_ID = st.secrets["TEMP_FOLDER_ID"]
            GAS_URL = st.secrets["GAS_URL"]

            # 3. メタデータ設定（まずは一時フォルダへ）
            file_metadata = {
                'name': uploaded_file.name,
                'parents': [TEMP_FOLDER_ID]
            }

            media = MediaFileUpload(
                temp_file_path, 
                mimetype='video/mp4',
                chunksize=1024 * 1024,
                resumable=True
            )

            status_text.text("Googleドライブへアップロード中...")
            
            request = drive_service.files().create(
                body=file_metadata, 
                media_body=media, 
                fields='id, webViewLink'
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress_percent = int(status.progress() * 100)
                    progress_bar.progress(progress_percent)
                    status_text.text(f"ドライブ送信進捗: {progress_percent}%")

            file_id = response.get('id')
            file_url = response.get('webViewLink')
            
            st.success("✅ Googleドライブへの一時保存に成功しました！")
            
            # 4. GASへの通知（生徒番号と、アップロードしたファイルのIDを一緒に送る）
            status_text.text("GASシステムがスプレッドシートのマスターからフォルダIDを検索中...")
            
            payload = {
                "status": "success",
                "student_id": student_id, # GAS側でマスターを探すためのキー
                "file_name": uploaded_file.name,
                "file_id": file_id,
                "file_url": file_url
            }
            
            gas_response = requests.post(GAS_URL, json=payload, timeout=30)
            
            if gas_response.status_code == 200:
                st.success("🎉 スプレッドシートのマスターに基づくフォルダ仕分け・記録が完了しました！")
                st.info(f"システムからの返答: {gas_response.text}")
            else:
                st.error(f"⚠️ ドライブ保存は成功しましたが、GAS側の処理でエラーが発生しました (Status: {gas_response.status_code})")

        except Exception as e:
            st.error(f"🚨 エラーが発生しました:\n{e}")
        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
else:
    if student_id == "" and uploaded_file is not None:
        st.warning("⚠️ 生徒番号を入力してください。")
