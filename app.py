import streamlit as st
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

st.title("生徒向け 倒立見本動画アップローダー")
st.write("34MBの動画ファイルを安全にGoogleドライブへアップロードし、システム（GAS）へ記録します。")

# 画面からファイルを選択できるようにする
uploaded_file = st.file_uploader("生徒に見せる動画（MP4形式）を選択してください", type=["mp4"])

if uploaded_file is not None:
    if st.button("Googleドライブへ送信を開始"):
        
        # APIのMediaFileUploadに渡すために、一時的にファイルを保存する
        temp_file_path = f"temp_{uploaded_file.name}"
        with open(temp_file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # 画面上の進捗表示エリアを準備
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.text("Google Drive API 認証中...")

        try:
            # 1. 認証設定（Streamlit Secrets から辞書として読み込む）
            SCOPES = ['https://www.googleapis.com/auth/drive']
            service_account_info = st.secrets["gcp_service_account"]
            
            creds = service_account.Credentials.from_service_account_info(
                service_account_info, scopes=SCOPES)
            
            drive_service = build('drive', 'v3', credentials=creds)

            # 2. SecretsからフォルダIDとGASのURLを取得
            FOLDER_ID = st.secrets["FOLDER_ID"]
            GAS_URL = st.secrets["GAS_URL"]

            # 3. アップロードするファイルのメタデータ設定
            file_metadata = {
                'name': uploaded_file.name,
                'parents': [FOLDER_ID]
            }

            # 4. 大容量ファイル用に1MBずつ分割(チャンク)して送信する設定
            media = MediaFileUpload(
                temp_file_path, 
                mimetype='video/mp4',
                chunksize=1024 * 1024,  # 1MB単位
                resumable=True
            )

            status_text.text("Googleドライブへアップロード中（34MB）...")
            
            # 5. Googleドライブへレジュマブル（分割）アップロードを実行
            request = drive_service.files().create(
                body=file_metadata, 
                media_body=media, 
                fields='id, webViewLink'
            )
            
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    # プログレスバーの表示を更新
                    progress_percent = int(status.progress() * 100)
                    progress_bar.progress(progress_percent)
                    status_text.text(f"ドライブ送信進捗: {progress_percent}%")

            # ドライブへのアップロード完了時の情報取得
            file_id = response.get('id')
            file_url = response.get('webViewLink')
            
            st.success("✅ Googleドライブへのアップロードに成功しました！")
            
            # 6. GASへの通知処理（重いデータではなく、URL文字列だけを送る）
            status_text.text("GASシステム（スプレッドシート等）にURLを記録中...")
            
            payload = {
                "status": "success",
                "file_name": uploaded_file.name,
                "file_id": file_id,
                "file_url": file_url
            }
            
            # 軽いデータ送信なので、通常のタイムアウト30秒で確実に間に合います
            gas_response = requests.post(GAS_URL, json=payload, timeout=30)
            
            if gas_response.status_code == 200:
                st.success("🎉 GASへのURL同期・記録が完了しました！")
                st.info(f"GASからの返答: {gas_response.text}")
            else:
                st.error(f"⚠️ ドライブ保存は成功しましたが、GASへの記録に失敗しました (Status: {gas_response.status_code})")

        except requests.exceptions.Timeout:
            st.error("🚨 GASへの記録中にタイムアウトが発生しました。GASのコード(doPost)が重い処理になっていないか確認してください。")
        except Exception as e:
            st.error(f"🚨 エラーが発生しました:\n{e}")
        
        finally:
            # サーバーを綺麗にするため、一時ファイルを確実に削除する
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
