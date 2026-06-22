import streamlit as st
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

# ==========================================
# 共通設定（Secretsから取得）
# ==========================================
try:
    GAS_URL = st.secrets["GAS_URL"]
    TEMP_FOLDER_ID = st.secrets["TEMP_FOLDER_ID"]
    service_account_info = st.secrets["gcp_service_account"]
except Exception as e:
    st.error("🚨 StreamlitのSecrets設定が読み込めません。管理画面の設定を確認してください。")

# ==========================================
# サイドバーによるメニュー切り替え
# ==========================================
st.sidebar.title("ナビゲーション")
menu = st.sidebar.radio("メニューを選択してください", ["生徒メニュー", "先生メニュー"])

# ---【生徒メニュー】------------------------------------
if menu == "生徒メニュー":
    st.title("🏃 生徒向けメニュー")
    st.write("各自の動画をアップロードして、先生へ提出しましょう。")
    
    # 生徒用の機能やメッセージをここに配置
    st.info("今日の課題：倒立のフォームチェック動画（30秒以内）")
    # ※以前の生徒用メニューにあったコードがあれば、ここに追記できます。


# ---【先生メニュー（動画アップローダー）】------------------
elif menu == "先生メニュー":
    st.title("👨‍🏫 先生向けメニュー")
    st.write("生徒に見せる見本動画（34MB等の大容量ファイル）をGoogleドライブへアップロードし、マスターデータと同期します。")

    # 1. 生徒を特定するための入力欄（スプレッドシートの検索キー）
    student_id = st.text_input("対象の生徒番号（またはクラス名など）を入力してください")
    uploaded_file = st.file_uploader("生徒に見せる動画（MP4形式）を選択してください", type=["mp4"])

    if uploaded_file is not None and student_id != "":
        if st.button("Googleドライブへ送信を開始"):
            
            # API用に一時ファイルをローカルに保存
            temp_file_path = f"temp_{uploaded_file.name}"
            with open(temp_file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # 画面上の進捗表示エリア
            progress_bar = st.progress(0)
            status_text = st.empty()
            status_text.text("Google Drive API 認証中...")

            try:
                # 2. Google Drive API 認証
                SCOPES = ['https://www.googleapis.com/auth/drive']
                creds = service_account.Credentials.from_service_account_info(
                    service_account_info, scopes=SCOPES)
                drive_service = build('drive', 'v3', credentials=creds)

                # 3. メタデータ設定（一時保存フォルダへ）
                file_metadata = {
                    'name': uploaded_file.name,
                    'parents': [TEMP_FOLDER_ID]
                }

                media = MediaFileUpload(
                    temp_file_path, 
                    mimetype='video/mp4',
                    chunksize=1024 * 1024, # 1MB単位で分割送信
                    resumable=True
                )

                status_text.text("Googleドライブへ大容量アップロード中...")
                
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
                
                # 4. GASへの通知
                status_text.text("GASシステムがスプレッドシートのマスターからフォルダIDを検索中...")
                
                payload = {
                    "status": "success",
                    "student_id": student_id,
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
