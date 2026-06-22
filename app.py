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
    st.error("🚨 StreamlitのSecrets設定が読み込めません。管理画面の設定を確認してください。")
    st.stop()

# ==========================================
# 2. マスターデータ（プルダウン用）
# ==========================================
# 学校・クラスのマスター
SCHOOL_MASTER = {
    "第一中学校": ["1年1組", "1年2組", "2年1組", "2年2組"],
    "第二中学校": ["1組", "2組", "3組"],
    "北野高校": ["1年A組", "1年B組", "2年A組", "2年B組"]
}

# ★追加：先生が用意した「お手本動画」のマスターリスト
# ※ URLの部分には、Googleドライブの「リンクを知っている全員が閲覧可能」に設定した動画の共有URLなどを入れてください。
MODEL_VIDEOS = {
    "レベル1：壁倒立（キープの練習）": {
        "url": "https://www.w3schools.com/html/mov_bbb.mp4", # テスト用のダミー動画URLです。本番環境のURLに差し替えてください
        "points": "肩をしっかり入れて、顎を引きすぎないように意識しましょう。"
    },
    "レベル2：補助付き倒立（バランス感覚）": {
        "url": "https://www.w3schools.com/html/movie.mp4",
        "points": "補助の人に腰を支えてもらい、一直線の姿勢を覚えましょう。"
    },
    "レベル3：壁なし倒立（完成形）": {
        "url": "https://www.w3schools.com/html/mov_bbb.mp4",
        "points": "指先と手のひら全体で地面を掴むようにしてバランスを取ります。"
    }
}

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
    st.subheader("1. 今日取り組むお手本を選ぶ")
    
    # ★追加：お手本動画の選択プルダウン
    selected_model_name = st.selectbox(
        "今日挑戦するメニューを選んでください",
        list(MODEL_VIDEOS.keys())
    )
    
    # 選ばれたお手本の詳細と動画を表示
    model_info = MODEL_VIDEOS[selected_model_name]
    st.info(f"💡 **意識するポイント:** {model_info['points']}")
    
    # 画面上でお手本動画を再生可能にする
    st.video(model_info["url"])
    
    st.markdown("---")
    st.subheader("2. あなたの情報を入力")
    
    # 生徒情報入力プルダウン
    student_school = st.selectbox("学校名を選択してください", list(SCHOOL_MASTER.keys()), key="student_school")
    student_class = st.selectbox("クラスを選択してください", SCHOOL_MASTER[student_school], key="student_class")
    student_id = st.text_input("生徒番号、または氏名を入力してください")
    
    # （任意）生徒側からも動画を提出したり、確認完了ボタンを押したりする機能をここに拡張できます
    if st.button("今日の取り組みを記録（確認送信）"):
        if student_id != "":
            st.success(f"🎉 {student_id}さんの 「{selected_model_name}」 への取り組みを記録しました！（※必要に応じてGASへ送信する処理を追加できます）")
        else:
            st.warning("⚠️ 記録のために生徒番号または氏名を入力してください。")


# ---【先生メニュー（動画アップローダー）】------------------
elif menu == "先生メニュー":
    st.title("👨‍🏫 先生向けメニュー")
    st.write("生徒に見せる見本動画（大容量ファイル対応）をGoogleドライブへアップロードし、スプレッドシートのマスターデータと同期します。")

    st.subheader("対象生徒・クラスの指定")
    
    teacher_school = st.selectbox("学校名を選択してください", list(SCHOOL_MASTER.keys()), key="teacher_school")
    teacher_class = st.selectbox("クラスを選択してください", SCHOOL_MASTER[teacher_school], key="teacher_class")
    target_id = st.text_input("対象の生徒番号、または識別IDを入力してください")
    
    st.markdown("---")
    st.subheader("動画ファイルのアップロード")
    uploaded_file = st.file_uploader("生徒に見せる動画（MP4形式、34MB等も対応）を選択してください", type=["mp4"])

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

                # 一時保存フォルダへ送信
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
                
                # GASへの通知
                status_text.text("GAS経由でスプレッドシートのマスターから対象フォルダを検索・移動中...")
                
                payload = {
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
                    st.success("🎉 スプレッドシートのマスターに基づく、本命フォルダへの仕分け・URL記録が完了しました！")
                    st.info(f"システム（GAS）からの返答: {gas_response.text}")
                else:
                    st.error(f"⚠️ ドライブ保存は成功しましたが、GAS側の仕分け処理でエラーが発生しました (Status: {gas_response.status_code})")

            except Exception as e:
                st.error(f"🚨 アップロード中にエラーが発生しました:\n{e}")
            finally:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
    else:
        if uploaded_file is not None and target_id == "":
            st.warning("⚠️ 識別用の生徒番号またはIDを入力してください。")
