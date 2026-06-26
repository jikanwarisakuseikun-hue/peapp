import streamlit as st
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import os
import av  # OpenCVの代わりにPyAVを使用
import mediapipe as mp
import numpy as np

st.set_page_config(page_title="AI採点機能付き 倒立見本動画管理システム", layout="centered")

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
# 2. GASから全てのマスタデータを自動取得
# ==========================================
@st.cache_data(ttl=300)
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

MASTER_DATA = load_all_master_data()
SCHOOL_MASTER = MASTER_DATA.get("schools", {})
SCHOOL_PASSWORDS = MASTER_DATA.get("passwords", {})
MODEL_VIDEOS = MASTER_DATA.get("videos", {})


# ==========================================
# 3. AI骨格解析＆採点ロジック (OpenCV不使用版)
# ==========================================
def calculate_angle(a, b, c):
    """3点の座標からなす角（角度）を計算する関数"""
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)
    
    radians = np.arctan2(c[1]-b[1], c[0]-b[0]) - np.arctan2(a[1]-b[1], a[0]-b[0])
    angle = np.abs(radians*180.0/np.pi)
    
    if angle > 180.0:
        angle = 360 - angle
    return angle

def analyze_pose_and_score(video_path):
    """PyAVとMediaPipeを使用して動画を解析し、スコアを算出するコアエンジン"""
    mp_pose = mp.solutions.pose
    best_score = 0
    feedback_msg = "倒立の姿勢が検出できませんでした。全身が写るように撮影してください。"
    
    try:
        # OpenCVの代わりにPyAVで動画をオープン
        container = av.open(video_path)
        stream = container.streams.video[0]
        
        with mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5) as pose:
            # 動画のフレームを1枚ずつループ処理
            for frame in container.decode(stream):
                # PyAVのフレームを直接RGBのNumpy配列に変換
                image = frame.to_ndarray(format='rgb24')
                results = pose.process(image)
                
                if results.pose_landmarks:
                    landmarks = results.pose_landmarks.landmark
                    
                    # 左半身の重要関節（肩・腰・膝）をサンプリング
                    shoulder = [landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].x, landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER.value].y]
                    hip = [landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].x, landmarks[mp_pose.PoseLandmark.LEFT_HIP.value].y]
                    knee = [landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].x, landmarks[mp_pose.PoseLandmark.LEFT_KNEE.value].y]
                    
                    hip_angle = calculate_angle(shoulder, hip, knee)
                    angle_diff = abs(180.0 - hip_angle)
                    
                    # 理想の180度（一直線）からのズレに基づき100点満点で減点
                    current_score = int(100 - (angle_diff * 2.5))
                    current_score = max(0, min(100, current_score))
                    
                    if current_score > best_score:
                        best_score = current_score
                        if best_score >= 90:
                            feedback_msg = f"素晴らしい！体が完全に一直線（腰の角度: {hip_angle:.1f}度）に伸びています。この調子でキープ時間を伸ばしましょう！"
                        elif best_score >= 75:
                            feedback_msg = f"お見事！かなり綺麗な倒立です（腰の角度: {hip_angle:.1f}度）。もう少しお腹を引き締めると、さらに軸が安定します。"
                        else:
                            feedback_msg = f"少し腰が「くの字」に曲がっているか、反ってしまっています（腰の角度: {hip_angle:.1f}度）。お手本動画を見て、肩から足先まで一直線にする意識を持ちましょう。"
    except Exception as e:
        feedback_msg = f"動画の解析中にエラーが発生しました: {e}"
        
    return best_score, feedback_msg


# ==========================================
# 4. 画面レイアウト
# ==========================================
st.sidebar.title("ナビゲーション")
menu = st.sidebar.radio("メニューを選択してください", ["生徒メニュー", "先生メニュー"])


# ---【生徒メニュー（AI自動採点機能搭載）】------------------------------------
if menu == "生徒メニュー":
    st.title("🏃 AI採点対応・生徒メニュー")
    st.write("今日取り組むお手本を確認し、動画を提出してAIに採点してもらいましょう！")
    
    st.markdown("---")
    st.subheader("1. あなたの情報を入力")
    
    student_school = st.selectbox("学校名を選択してください", list(SCHOOL_MASTER.keys()), key="student_school")
    classes = SCHOOL_MASTER.get(student_school, [])
    student_class = st.selectbox("クラスを選択してください", classes, key="student_class")
    student_id = st.text_input("生徒番号、または氏名を入力してください（例：05番 佐藤）")
    
    st.markdown("---")
    st.subheader("2. 今日取り組むお手本を選ぶ")
    
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
    st.subheader("3. 自分の動画を撮影・提出してAI採点！")
    student_file = st.file_uploader("撮影した自分の動画（MP4形式など）を選択してください", type=["mp4", "mov", "avi"])
    
    if student_file is not None:
        if st.button("AI採点＆動画を提出する"):
            if student_id == "":
                st.warning("⚠️ 生徒番号または氏名を必ず入力してください。")
            elif not available_videos:
                st.error("⚠️ 技のメニューが正しく選択されていません。")
            else:
                ext = os.path.splitext(student_file.name)[1]
                custom_filename = f"{student_class}_{student_id}_{selected_model_name}{ext}"
                temp_file_path = f"temp_{custom_filename}"
                
                with open(temp_file_path, "wb") as f:
                    f.write(student_file.getbuffer())

                status_text = st.empty()
                status_text.info("🤖 AIがあなたの骨格を抽出中... 動画を解析しています...")
                
                score, feedback = analyze_pose_and_score(temp_file_path)
                
                st.markdown(f"## 📊 AI採点結果: **{score} 点** / 100点満点")
                if score >= 80:
                    st.success(feedback)
                elif score >= 60:
                    st.warning(feedback)
                else:
                    st.error(feedback)
                
                progress_bar = st.progress(0)
                status_text.text("Googleドライブへ提出動画を送信中...")

                try:
                    SCOPES = ['https://www.googleapis.com/auth/drive']
                    creds = service_account.Credentials.from_service_account_info(
                        service_account_info, scopes=SCOPES)
                    drive_service = build('drive', 'v3', credentials=creds)

                    final_filename = f"【{score}点】{student_class}_{student_id}_{selected_model_name}{ext}"

                    file_metadata = {
                        'name': final_filename,
                        'parents': [TEMP_FOLDER_ID]
                    }

                    media = MediaFileUpload(
                        temp_file_path, 
                        mimetype='video/mp4',
                        chunksize=1024 * 1024,
                        resumable=True
                    )
                    
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

                    file_id = response.get('id')
                    file_url = response.get('webViewLink')
                    
                    status_text.text("クラス別フォルダへの自動仕分け中...")
                    
                    payload = {
                        "action": "upload_video",
                        "status": "success",
                        "school": student_school,
                        "class": student_class,
                        "student_id": f"{student_id}_(Score:{score})", 
                        "file_name": final_filename,
                        "file_id": file_id,
                        "file_url": file_url
                    }
                    
                    gas_response = requests.post(GAS_URL, json=payload, timeout=30)
                    
                    if gas_response.status_code == 200:
                        st.success(f"🎉 動画の提出とAI仕分けがすべて完了しました！送信お疲れ様でした！")
                        if score >= 80:
                            st.balloons()
                    else:
                        st.error("⚠️ ドライブ保存は成功しましたが、GAS仕分けでエラーが発生しました。")

                except Exception as e:
                    st.error(f"🚨 提出エラーが発生しました:\n{e}")
                finally:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    status_text.empty()


# ---【先生メニュー】--------------------------------------------------------
elif menu == "先生メニュー":
    st.title("👨‍🏫 先生向けメニュー")
    st.subheader("ログイン認証")
    
    auth_school = st.selectbox("学校名を選択してください", list(SCHOOL_MASTER.keys()), key="auth_school")
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
                        st.success("🎉 本命フォルダへの仕分けが完了しました！")
                    else:
                        st.error("⚠️ GAS側の仕分け処理でエラーが発生しました。")

                except Exception as e:
                    st.error(f"🚨 アップロード中にエラーが発生しました:\n{e}")
                finally:
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
