import streamlit as st
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os

# ページの設定
st.set_page_config(page_title="学校向け 倒立見本動画管理システム", layout="centered")

# ==========================================
# 1. 共通設定・環境チェック（Secretsから取得）
# ==========================================
try:
    GAS_URL = st.secrets["GAS_URL"]
    TEMP_FOLDER_ID = st.secrets["TEMP_FOLDER_ID"]
    service_account_info = st.secrets["gcp_service_account"]
except Exception as e:
    st.error("🚨 StreamlitのSecrets設定が読み込めません。管理画面を確認してください。")
    st.stop()


# ==========================================
# 2. GAS（スプレッドシート）から全てのマスタデータを自動取得
# ==========================================
@st.cache_data(ttl=300)  # 5分間キャッシュ
def load_all_master_data():
    try:
        response = requests.get(GAS_URL, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        st.error(f"⚠️ GASからのマスタデータ取得に失敗しました。 エラー: {e}")
    
    return {
        "schools": {"第一中学校（同期失敗）": ["1組"]},
        "passwords": {},
        "videos": {"エラー：技が読み込めませんでした": {"url": "", "points": ""}}
    }

# マスタデータの読み込み
MASTER_DATA = load_all_master_data()
SCHOOL_MASTER = MASTER_DATA.get("schools", {})
SCHOOL_PASSWORDS = MASTER_DATA.get("passwords", {})
MODEL_VIDEOS = MASTER_DATA.get("videos", {})


# ==========================================
# 3. サイドバーによるメニュー切り替え
# ==========================================
st.sidebar.title("ナビゲーション")
menu = st.sidebar.radio("メニューを選択してください", ["生徒メニュー", "先生メニュー"])


# ---【生徒メニュー】------------------------------------
if menu == "生徒メニュー":
    st.title("🏃 生徒向けメニュー")
    st.write("今日取り組むお手本を選んで練習し、結果を報告・提出しましょう。")
    
    st.markdown("---")
    st.subheader("1. あなたの情報を入力")
    
    student_school = st.selectbox("学校名を選択してください", list(SCHOOL_MASTER.keys()), key="student_school")
    classes = SCHOOL_MASTER.get(student_school, [])
    student_class = st.selectbox("クラスを選択してください", classes, key="student_class")
    student_id = st.text_input("生徒番号、または氏名を入力してください")
    
    st.markdown("---")
    st.subheader("2. 今日取り組むお手本を選ぶ")
    
    # 選ばれたクラスに応じて、表示する動画リストを動的に作成
    class_videos = MODEL_VIDEOS.get(student_class, {})
    common_videos = MODEL_VIDEOS.get("共通", {})
    available_videos = {**common_videos, **class_videos}
    
    if available_videos:
        selected_model_name = st.selectbox("今日挑戦するメニューを選んでください", list(available_videos.keys()))
        model_info = available_videos[selected_model_name]
        st.info(f"💡 **意識するポイント:** {model_info['points']}")
        
        if model_info["url"]:
            st.video(model_info["url"])
        else:
            st.warning("⚠️ この技の見本動画はまだ登録されていません。")
    else:
        st.warning("⚠️ 選択されたクラス向けのお手本動画が登録されていません。")
        
    st.markdown("---")
    if st.button("今日の取り組みを記録（確認送信）"):
        if student_id != "" and available_videos:
            st.success(f"🎉 {student_id}さんの 「{selected_model_name}」 への取り組みを記録しました！")
        else:
            st.warning("⚠️ 記録のために生徒番号または氏名を入力してください。")


# ---【先生メニュー（パスワードロック付き・学校連動版）】------------------
elif menu == "先生メニュー":
    st.title("👨‍🏫 先生向けメニュー")
    st.subheader("ログイン認証")
    
    auth_school = st.selectbox("学校名を選択してください", list(SCHOOL_MASTER.keys()), key="auth_school")
    # 預かっているパスワードを画面に強制表示して確認する（テスト後消してください）
st.write(f"🔍 システムが認識している正しいパスワード: 『{correct_password}』")
    password_input = st.text_input(f"「{auth_school}」の先生用パスワードを入力してください", type="password")
    correct_password = SCHOOL_PASSWORDS.get(auth_school, "")
    
    if password_input == "":
        st.info("🔓 先生用メニューを表示するにはパスワードが必要です。")
    elif password_input != correct_password:
        st.error("❌ パスワードが違います。アクセスできません。")
    else:
        st.success(f"✅ {auth_school} の管理画面として認証されました。")
        st.write("生徒に見せる見本動画をGoogleドライブへアップロードし、スプレッドシートのマスターデータと同期します。")

        st.markdown("---")
        st.subheader("対象クラスの指定")
        
        teacher_school = auth_school
        t_classes = SCHOOL_MASTER.get(teacher_school, [])
        teacher_class = st.selectbox("クラスを選択してください", t_classes, key="teacher_class")
        
        upload_type = st.radio("配布対象を選んでください", ["クラス全員向け（共通の見本動画）", "特定の生徒向け（個別指導用）"])
        
        if upload_type == "特定の生徒向け（個別指導用）":
            target_id = st.text_input("対象の生徒番号、または識別IDを入力してください")
        else:
            target_id = "全員"
            st.info("💡 この動画は選択されたクラスの全員向け（共通見本）として処理されます。")
        
        st.markdown("---")
        st.subheader("動画ファイルのアップロード")
        uploaded_file = st.file_uploader("生徒に見せる動画（MP4形式）を選択してください", type=["mp4"])

        if uploaded_file is not None and target_id != "":
            if st.button("Googleドライブへの送信・仕分けを開始"):
                
                temp_file_path = f"temp_{uploaded_file.name}"
                with open(temp_file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                progress_bar = st.progress(0)
                status_text = st.empty()
                status_text.text("Google Drive API 認証中...")

                try:
                    # Google Drive API 認証
                    SCOPES = ['https://www.googleapis.com/auth/drive']
                    creds = service_account.Credentials.from_service_account_info(
                        service_account_info, scopes=SCOPES)
                    drive_service = build('drive', 'v3', credentials=creds)

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
                    
                    st.success("✅ Googleドライブへの保存に成功しました！")
                    status_text.text("GAS経由でフォルダを検索・移動中...")
                    
                    payload = {
                        "action": "upload_video",
                        "status": "success",
                        "school": teacher_school,
                        "class": teacher_class,
                        "student_id": target_id,   
                        "file_name": uploaded_file.name,
                        "file_id": file_id,
                        "file_url": file_url
                    }
                    
                    gas_response = requests.post(GAS_URL, json=payload, timeout=30)
                    
                    if gas_response.status_code == 200:
                        st.success("🎉 本命フォルダへの仕分け・URL記録が完了しました！")
                        st.info(f"システムからの返答: {gas_response.text}")
                    else:
                        st.error(f"⚠️ GAS側の仕分け処理でエラーが発生しました (Status: {gas_response.status_code})")

                except Exception as e:
                    st.error(f"🚨 アップロード中にエラーが発生しました:\n{e}")
                finally:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
        else:
            if uploaded_file is not None and target_id == "":
                st.warning("⚠️ 識別用の生徒番号またはIDを入力してください。")
