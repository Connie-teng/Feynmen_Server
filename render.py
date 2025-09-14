import openai
from dotenv import find_dotenv, load_dotenv
import time
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_file, Response
import pymysql
import os
import urllib.parse
import traceback
import unicodedata
import tempfile  # 用於處理臨時文件
import re  # 用於正則表達式處理
from elevenlabs import Voice, generate, set_api_key, VoiceSettings
import io #新增
import json
from functools import lru_cache
import noisereduce as nr
import soundfile as sf
import numpy as np
from flask_cors import CORS  
import cloudinary
import cloudinary.uploader

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY") #新增
set_api_key(ELEVENLABS_API_KEY) #新增
DATABASE_URL = os.getenv("DATABASE_URL")
client = openai.OpenAI()
model = "gpt-4.1-mini-2025-04-14"
assist_object = None
audio_cache = {} #新增
# assist_id = "asst_5e5dhB3559PWxjwL31c626Co"
# thread_id = "thread_opEGrVqFPR05WXYVjejaaQFg"
# vector_id ="vs_j7PxwFEhPGN06nKpk7YG4qPD"

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# 解析 MySQL 連線資訊（如果你手動設定，直接填入 host、port、user、password、db）
def get_db_connection():
    return pymysql.connect(
        host="yamanote.proxy.rlwy.net",
        port=54767,
        user="root",
        password="iltFdQcGSTrQoiYsydTrUnBAWqMpSBIV",
        database="railway",
        cursorclass=pymysql.cursors.DictCursor  # 讓回傳結果變成字典格式
    )


# == Handle Unity request == 新的在下方
'''@app.route('/chat', methods=['POST'])
def chat():

    try:
        # Get user input from Unity's request
        data = request.get_json()
        action = data.get('action', '')
        assist_id = None
        thread_id = None
        vector_id = None

        if not action:
            return jsonify({"error": "No action can been found."}), 400
        
        match (action):
            case "message":
                # Create message with user input
                assist_id = data.get('assistant_id', '')
                thread_id = data.get('thread_id', '')
                
                message = client.beta.threads.messages.create(
                    thread_id= thread_id,
                    role="user",
                    content=data.get('message', '')
                )

                # Start a run (this will process the message with the assistant)
                run = client.beta.threads.runs.create(
                    thread_id= thread_id,
                    assistant_id= assist_id
                )

                response = wait_for_run_completion(client, thread_id, run.id, 5)

                return jsonify({"action": "message",
                                "message": response}), 200
            
            case "delete_assistant":
                assist_id = data.get('assistant_id', '')
                thread_id = data.get('thread_id', '')
                client.beta.assistants.delete(assist_id)
                client.beta.threads.delete(thread_id)
                response = "Assistant deleted!\n"
                return jsonify({"action": "delete_assistant",
                                "message": "Assistant deleted!"}), 200
            case "upload_ToC":
                
                chapters = data.get("chapters", [])
                course_id = data.get("course_id", " ")
                # **存入資料庫**
                connection = get_db_connection()
                with connection.cursor() as cursor:
                    for idx, chapter in enumerate(chapters, start=1):
                        chapter_title = chapter.get("title")  # 取得每個章節的 title
                        print(chapter_title)
                        sql = """
                        INSERT INTO CourseChapters (course_id, chapter_name, chapter_type, order_index)
                        VALUES (%s, %s, %s, %s)
                        """
                        cursor.execute(sql, (course_id, chapter_title, "one_to_one", idx))  # 假設 course_id = 1
                        cursor.execute(sql, (course_id, chapter_title, "classroom", idx))
                
                connection.commit()
                connection.close()

                return jsonify({"message": "Chapters uploaded successfully!"})

            
            case _:
                return jsonify({"error": "Invalid action"}), 400
        

    except Exception as e:
        logging.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({"error": "Something went wrong"}), 500'''

# 新增清理函數
def clean_text(text):
    # 定義需要過濾的內容類型
    unwanted_patterns = {
        'advertisement': [
            r'請不吝點贊訂閱轉發打賞',
            r'支持明鏡與點點欄目',
            r'歡迎訂閱',
            r'點贊關注',
            r'轉發分享',
            r'訂閱我的頻道',
            r'按讚訂閱',
            r'分享給更多人',
            r'支持我們',
            r'感謝觀看'
        ],
        'social_media': [
            r'@\w+',  # 社交媒體用戶名
            r'#\w+',  # 話題標籤
            r'https?://\S+'  # URL
        ],
        'noise': [
            r'\[.*?\]',  # 方括號內容
            r'\(.*?\)',  # 圓括號內容
            r'【.*?】',  # 中文方括號內容
            r'（.*?）',  # 中文圓括號內容
            r'唉{2,}',  # 重複的"唉"
            r'ayy{2,}',  # 重複的"ayy"
            r'呃{2,}',  # 重複的"呃"
            r'嗯{2,}',  # 重複的"嗯"
            r'啊{2,}',  # 重複的"啊"
            r'哦{2,}',  # 重複的"哦"
            r'。{2,}',  # 重複的句號
            r'，{2,}',  # 重複的逗號
            r'！{2,}',  # 重複的驚嘆號
            r'？{2,}',  # 重複的問號
            r'\.{2,}',  # 重複的英文句號
            r',{2,}',   # 重複的英文逗號
            r'!{2,}',   # 重複的英文驚嘆號
            r'\?{2,}'   # 重複的英文問號
        ]
    }
    
    # 應用所有過濾規則
    cleaned_text = text
    for category, patterns in unwanted_patterns.items():
        for pattern in patterns:
            cleaned_text = re.sub(pattern, '', cleaned_text)
    
    # 只保留中文、英文、數字和必要的標點符號
    cleaned_text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?，。！？:;""''()（）:：;；]', '', cleaned_text)
    
    # 清理多餘的空格
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
    cleaned_text = cleaned_text.strip()
    
    return cleaned_text

# == Handle Unity request ==
@app.route('/chat', methods=['POST'])
def chat():
    try:
        # Get user input from Unity's request
        data = request.get_json()
        action = data.get('action', '')
        assist_id = None
        thread_id = None
        vector_id = None

        if not action:
            return jsonify({"error": "No action can been found."}), 400
        
        match (action):
            case "message":
                # 清理用戶輸入的訊息
                user_message = data.get('message', '')
                cleaned_message = clean_text(user_message)
                
                # 記錄原始和清理後的訊息
                logging.info(f"原始用戶訊息: {user_message}")
                logging.info(f"清理後訊息: {cleaned_message}")
                
                # Create message with cleaned user input
                assist_id = data.get('assistant_id', '')
                thread_id = data.get('thread_id', '')
                
                message = client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=cleaned_message
                )

                # Start a run (this will process the message with the assistant)
                run = client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=assist_id
                )

                response = wait_for_run_completion(client, thread_id, run.id, 10)

                return jsonify({
                    "action": "message",
                    "message": response
                }), 200
            
            case "delete_assistant":
                assist_id = data.get('assistant_id', '')
                thread_id = data.get('thread_id', '')
                client.beta.assistants.delete(assist_id)
                client.beta.threads.delete(thread_id)
                response = "Assistant deleted!\n"
                return jsonify({
                    "action": "delete_assistant",
                    "message": "Assistant deleted!"
                }), 200
                
            case "upload_ToC":
                chapters = data.get("chapters", [])
                course_id = data.get("course_id", " ")
                # **存入資料庫**
                connection = get_db_connection()
                with connection.cursor() as cursor:
                    for idx, chapter in enumerate(chapters, start=1):
                        chapter_title = chapter.get("title")  # 取得每個章節的 title
                        print(chapter_title)
                        sql = """
                        INSERT INTO CourseChapters (course_id, chapter_name, chapter_type, order_index)
                        VALUES (%s, %s, %s, %s)
                        """
                        cursor.execute(sql, (course_id, chapter_title, "one_to_one", idx))
                        cursor.execute(sql, (course_id, chapter_title, "classroom", idx))
                
                connection.commit()
                connection.close()

                return jsonify({"message": "Chapters uploaded successfully!"})
            
            case _:
                return jsonify({"error": "Invalid action"}), 400

    except Exception as e:
        logging.error(f"Error in chat endpoint: {str(e)}")
        return jsonify({"error": "Something went wrong"}), 500

@app.route('/create', methods=['POST'])
def create():

    
    class_name = request.form.get('class_name')
    try:
        user_id = int(request.form.get('user_id'))
        course_type = int(request.form.get('course_type'))
    except (ValueError, TypeError):
        return "Invalid input type", 400
    
    course_format = None
    course_cloud_id = None

    print(class_name)
    new_assistant_1 = create_new_assistant(class_name + " first-part", "teacher")
    new_thread_1 = client.beta.threads.create()
    new_assistant_2 = create_new_assistant(class_name + " second-part", "student")
    new_thread_2 = client.beta.threads.create()

    vector_id_1 = client.beta.assistants.retrieve(new_assistant_1.id).tool_resources.file_search.vector_store_ids[0]
    vector_id_2 = client.beta.assistants.retrieve(new_assistant_2.id).tool_resources.file_search.vector_store_ids[0]

    if(course_type < 0): #文字上傳模式
        print("Starting a Course ")
        course_format = "text"
        course_context = request.form.get('course_context')

        message = client.beta.threads.messages.create(
                    thread_id=new_thread_1.id,
                    role="user",
                    content= f"""這是使用者上傳的內容: {course_context}
                    不用回應，請等後續指示。"""
                )

        # Start a run (this will process the message with the assistant)
        run = client.beta.threads.runs.create(
            thread_id=new_thread_1.id,
            assistant_id=new_assistant_1.id
        )

        response = wait_for_run_completion(client, new_thread_1.id, run.id, 20)



    elif(course_type == 0):
        # 檢查是否有檔案被上傳
        print("Starting a Course with a file uploaded.")

        if 'file' not in request.files:
            return "No file found in request", 400

        file = request.files['file']
        encoded_filename = file.filename
        filename = urllib.parse.unquote(encoded_filename)
        course_format = request.form.get('course_format')
        

        # 儲存檔案到伺服器的某個路徑
        file_path = os.path.join('/tmp', filename)
        file.save(file_path)
        fileId = uploadFile(file_path)
        add_files_to_vector_store(vector_id_1, fileId)
        add_files_to_vector_store(vector_id_2, fileId)

        course_cloud_id = uploadFileToCloud(file_path)
        print(f"成功上傳到雲端: {course_cloud_id}")
        response = "File uploaded!\n"
        
        os.remove(file_path)

        

    else:
        fileId = None
        course_format = "pdf"
        print("Starting a Preset Course.")
        match(course_type):
            
            case 1:
                fileId = "file-BqhzdHDep9korGXi4qeevY"#IntroductionToStock.pdf
                course_cloud_id = "https://res.cloudinary.com/dni1rb4zi/raw/upload/v1747215633/feyndora/IntroductionToStock_uzdhjy.pdf"
                print("Chose Preset Course: IntroductionToStock")
            case 2:
                fileId = "file-JF1YiMrurHpN7MiVkjoKGt"#HypothesisTesting.pdf
                course_cloud_id = "https://res.cloudinary.com/dni1rb4zi/raw/upload/v1747215554/feyndora/HypothesisTesting_x6zwq2.pdf"
                print("Chose Preset Course: HypothesisTesting")
            case 3:
                fileId = "file-7WwsTFspmRSrNB3Lo66Bcj"#OrganizationDesign.pdf
                course_cloud_id = "https://res.cloudinary.com/dni1rb4zi/raw/upload/v1747215738/feyndora/OrganizationDesign_bdzdlm.pdf"
                print("Chose Preset Course: OrganizationDesign")

        print("Preset Course ID: " + fileId)
        add_files_to_vector_store(vector_id_1, fileId)
        add_files_to_vector_store(vector_id_2, fileId)
   


    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        #查詢使用者的卡
        query = """
        SELECT card_id
        FROM UserCards
        WHERE user_id = %s AND is_selected = 1
        """
        cursor.execute(query, (user_id,))

        result = cursor.fetchone()
        if result:
            card_id = result["card_id"]
            print("卡片 ID：", card_id)
        else:
            print("card_id 查無資料")

        # 插入課程資料
        insert_query = """
        INSERT INTO Courses (course_name, file_type, user_id, teacher_card_id, cloudinary_url) 
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (class_name, course_format, user_id, card_id, course_cloud_id))

        # 取得剛剛插入的課程 ID
        cursor.execute("SELECT LAST_INSERT_ID() as course_id;")
        course_id = cursor.fetchone()["course_id"]

        # ✅ `INSERT` 資料到 `Assistants` 表
        query = """
        INSERT INTO Assistants (course_id, assistant_id, thread_id, role)
        VALUES (%s, %s, %s, %s);
        """

        cursor.execute(query, (course_id, new_assistant_1.id, new_thread_1.id, "teacher"))
        cursor.execute(query, (course_id, new_assistant_2.id, new_thread_2.id, "student"))

        # ✅ **一次 commit()，提高效能**
        conn.commit()

    except Exception as e:
        # ❌ **如果出錯，回滾所有更改，確保資料一致**
        conn.rollback()
        print(f"❌ 資料庫錯誤: {e}")
        print("❌ 錯誤詳細：\n", traceback.format_exc())
        return jsonify({"error": str(e)}), 500

    finally:
        # ✅ **確保 cursor 和 conn 正確關閉**
        cursor.close()
        conn.close()
    
    print("準備Retrun")

    response_data = {
        "action": "upload_file and create assistant",
        "course_id": course_id,
        "assistant_id_1": new_assistant_1.id,
        "thread_id_1": new_thread_1.id,
        "assistant_id_2": new_assistant_2.id,
        "thread_id_2": new_thread_2.id,
        "cloud_link": course_cloud_id
    }

    # 美化印出 JSON（含中文不轉義）
    print(json.dumps(response_data, indent=2, ensure_ascii=False))

    response = jsonify(response_data)
    response.headers["Content-Type"] = "application/json"
    response.headers["Connection"] = "close"  # ✅ 關鍵：強制關閉連線
    return response, 200
                    
    
@app.route('/fetch', methods=['POST'])
def fetch_chatGPT_data():

    try:
        data = request.get_json()
        print("Received JSON:", data)

        course_id = data.get('course_id', '')
        role = data.get('role', '')

        if not course_id or not role:
            return jsonify({"error": "Missing parameters"}), 400


        conn = get_db_connection()
        cursor = conn.cursor()  

        # 查詢資料庫
        query = """
            SELECT * FROM Assistants
            WHERE course_id = %s AND role = %s
        """
        print(f"Executing SQL: {query} with params ({course_id}, {role})")


        cursor.execute(query, (course_id, role))
        result = cursor.fetchall()  # 拿取所有符合條件的資料

        cursor.close()
        conn.close()


        if result:
            first_result = result[0]  # 取第一筆資料
            # 回傳 assistant_id 和 thread_id
            return jsonify({
                "action": "fetch_chatGPT_data",
                "assistant_id": first_result["assistant_id"],
                "thread_id": first_result["thread_id"]
            }), 200
        else:
            return jsonify({"message": "No data found"}), 404

    except Exception as e:
        error_details = traceback.format_exc()  # 取得完整錯誤訊息
        print("ERROR TRACEBACK:\n", error_details)
        return jsonify({"error": str(e), "details": error_details}), 500
    
@app.route("/get_chapters", methods=["GET"])
def get_chapters():
    course_id = request.args.get("course_id", type=int)
    chapter_type = request.args.get("chapter_type", type=str)

    if not course_id or not chapter_type:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 查詢符合條件的目錄
        query = """
        SELECT chapter_id, chapter_name, order_index , is_completed
        FROM CourseChapters 
        WHERE course_id = %s AND chapter_type = %s
        ORDER BY order_index ASC
        """
        cursor.execute(query, (course_id, chapter_type))
        result = cursor.fetchall()

        print(type(result[0]))
        conn.close()
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get_cloud_link", methods=['POST'])
def get_cloud_link():
    try:
        data = request.get_json()
        print("Received JSON:", data)

        course_id = data.get('course_id', '')

        if not course_id:
            return jsonify({"error": "Missing parameters"}), 400


        conn = get_db_connection()
        cursor = conn.cursor()  

        # 查詢資料庫
        query = """
            SELECT cloudinary_url FROM Courses
            WHERE course_id = %s
        """
        print(f"Executing SQL: {query} with params ({course_id})")


        cursor.execute(query, (course_id,))
        result = cursor.fetchone()  # 拿取所有符合條件的資料

        cursor.close()
        conn.close()


        if result:
            cloud_link = result['cloudinary_url']  # 取第一筆資料
            # 回傳 assistant_id 和 thread_id
            return jsonify({
                "action": "get_cloud_url",
                "cloud_link": cloud_link
            }), 200
        else:
            return jsonify({"message": "No data found"}), 404

    except Exception as e:
        error_details = traceback.format_exc()  # 取得完整錯誤訊息
        print("ERROR TRACEBACK:\n", error_details)
        return jsonify({"error": str(e), "details": error_details}), 500
    



@app.route("/update_chapter_progress", methods=["POST"])
def update_chapter_progress():
    data = request.get_json()
    print("Received JSON:", data)

    try:
        course_id = int(data.get('course_id'))
        chapter_type = str(data.get('chapter_type')).strip().replace('\u200b', '').replace('\n', '').replace('\r', '').lower()
        order_index = int(data.get('order_index'))
        print("Query params:", course_id, chapter_type, order_index)
        print(f"🧪 原始 chapter_type = [{data.get('chapter_type')}] 長度 = {len(data.get('chapter_type'))}")
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid parameters: {e}"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 直接更新資料
        cursor.execute("""
            UPDATE CourseChapters
            SET is_completed = 1
            WHERE course_id = %s AND chapter_type = %s AND order_index = %s
        """, (course_id, chapter_type, order_index))

        # if cursor.rowcount == 0:
        #     print("❌ 查無資料：", course_id, chapter_type, order_index)
        #     return jsonify({"success": False, "message": "Chapter not found"}), 404

        print(f"✅ 成功更新：course_id={course_id}, chapter_type={chapter_type}, order_index={order_index}")
        conn.commit()
        return jsonify({"success": True}), 200

    except Exception as e:
        print("❌ Exception:", e)
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/update_score", methods=["POST"])
def update_score():
    data = request.get_json()
    print("Received JSON:", data)

    try:
        course_id = int(data.get('course_id'))
        user_id = int(data.get('user_id'))
        accuracy_score = int(data.get('precision'))
        expression_score = int(data.get('expressiveness'))
        understanding_score = int(data.get('comprehension'))
        interaction_score = int(data.get('interactivity'))

        
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid parameters: {e}"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
         # 新增一筆資料到 CourseReviews 表格
        cursor.execute("""
            INSERT INTO CourseReviews (
                course_id,
                user_id,
                accuracy_score,
                understanding_score,
                expression_score,
                interaction_score
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (course_id, user_id, accuracy_score, understanding_score, expression_score, interaction_score))

        daily_points = round((accuracy_score + understanding_score + expression_score + interaction_score)/4)
        
        cursor.execute("""
            INSERT INTO LearningPointsLog (
                user_id,
                date,
                daily_points
            ) VALUES (%s, CURRENT_DATE, %s)
        """, (user_id, daily_points))

        cursor.execute("""
            INSERT INTO CoursePointsLog(
                user_id,
                course_id,
                completed_date,
                earned_points
            ) VALUES (%s, %s, CURRENT_DATE, %s)
        """, (user_id, course_id, daily_points))

        cursor.execute("""
            UPDATE Users
                SET total_learning_points = total_learning_points + %s
                WHERE user_id = %s
            """, (daily_points, user_id))

        conn.commit()
        print(f"✅ 成功新增 review：course_id={course_id}, user_id={user_id}, 加分={daily_points}")
        return jsonify({"success": True}), 200

    except Exception as e:
        print("❌ Exception:", e)
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/update_comment", methods=["POST"])
def update_comment():
    data = request.get_json()
    print("Received JSON:", data)

    try:
        course_id = int(data.get('course_id'))
        user_id = int(data.get('user_id'))
        teacher_comment = data.get('teacher_comment')
        student1_feedback = data.get('student1_feedback')
        student2_feedback = data.get('student2_feedback')
        student3_feedback = data.get('student3_feedback')
        good_points = json.dumps(data.get('good_points'))  # 轉成 JSON 字串
        improvement_points = json.dumps(data.get('improvement_points'))  # 轉成 JSON 字串
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid parameters: {e}"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 檢查是否存在該筆資料
        cursor.execute("""
            SELECT review_id FROM CourseReviews
            WHERE course_id = %s AND user_id = %s
            LIMIT 1
        """, (course_id, user_id))

        print("Review Record is found...")
        result = cursor.fetchone()
        if not result:
            return jsonify({"success": False, "message": "Review not found"}), 404

        # 更新欄位
        cursor.execute("""
            UPDATE CourseReviews
            SET teacher_comment = %s,
                student1_feedback = %s,
                student2_feedback = %s,
                student3_feedback = %s,
                good_points = %s,
                improvement_points = %s
            WHERE course_id = %s AND user_id = %s
        """, (
            teacher_comment,
            student1_feedback,
            student2_feedback,
            student3_feedback,
            good_points,
            improvement_points,
            course_id,
            user_id
        ))

        conn.commit()
        print(f"✅ 成功更新 review：course_id={course_id}, user_id={user_id}")
        return jsonify({"success": True}), 200

    except Exception as e:
        print("❌ Exception:", e)
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

    # try:
    #     # 先找出該章節
    #     cursor.execute("""
    #         SELECT chapter_id FROM CourseChapters
    #         WHERE course_id = %s AND chapter_type = %s AND order_index = %s
    #     """, (course_id, chapter_type, order_index))

    #     result = cursor.fetchone()

    #     cursor.execute("""
    #         SELECT chapter_id, course_id, chapter_type, order_index, LENGTH(chapter_type)
    #         FROM CourseChapters
    #         WHERE course_id = %s
    #     """, (course_id,))
    #     print("📋 該課程的所有章節：")
    #     for row in cursor.fetchall():
    #         print(row)

    #     if result is None:
    #         print("❌ 查無資料：", course_id, chapter_type, order_index)
    #         return jsonify({"success": False, "message": "Chapter not found"}), 404
        
    #     # 如果是空 tuple 或其他非 None 值也擋一下
    #     if not isinstance(result, (tuple, list)) or len(result) == 0:
    #         print("❌ 查無資料（空值）:", course_id, chapter_type, order_index)
    #         return jsonify({"success": False, "message": "Chapter not found"}), 404

    #     print("🐞 result =", result, "type =", type(result))


    #     chapter_id = int(result[0])
    #     print("📘 章節 ID:", chapter_id, "TYPE:", type(chapter_id))
    #     print("相應章節... 設為完成中...")
    #     # 更新 is_completed
    #     cursor.execute("""
    #         UPDATE CourseChapters
    #         SET is_completed = 1
    #         WHERE chapter_id = %s
    #     """, (chapter_id,))

    #     print("✅ 成功更新章節 ID:", chapter_id)
    #     conn.commit()
    #     return jsonify({"success": True, "chapter_id": chapter_id}), 200

    # except Exception as e:
    #     print("❌ Exception:", e)   
    #     conn.rollback()
    #     return jsonify({"success": False, "message": str(e)}), 500

    # finally:
    #     cursor.close()
    #     conn.close()


@app.route("/activate_VR", methods=["POST"])
def activate_VR():
    data = request.get_json()
    course_id = data.get('course_id')
    user_id = data.get('user_id')

    if not course_id or not user_id:
        return jsonify({"success": False, "message": "Missing course_id or user_id"}), 400

    print("Activating VR for course: ", course_id, user_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 查找該 user_id 選擇的 teacher card
        cursor.execute("""
            SELECT card_id FROM UserCards
            WHERE user_id = %s AND is_selected = 1
            LIMIT 1
        """, (user_id,))
        card = cursor.fetchone()
        print("[DEBUG] Query result:", card)

        if not card:
            return jsonify({"success": False, "message": "No selected teacher card found for this user"}), 404

        teacher_card_id = card['card_id']
        print(teacher_card_id)

        # 更新 Courses 資料表
        cursor.execute("""
            UPDATE Courses
            SET is_vr_ready = 1,
                vr_started_at = CURRENT_TIMESTAMP,
                teacher_card_id = %s
            WHERE course_id = %s
        """, (teacher_card_id, course_id))

        if cursor.rowcount == 0:
            return jsonify({"success": False, "message": "Course not found"}), 404

        conn.commit()
        return jsonify({
            "success": True,
            "message": f"Course {course_id} marked as VR ready with teacher_card_id {teacher_card_id}"
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/deactivate_VR", methods=["POST"])
def deactivate_VR():
    data = request.get_json()
    print("📥 Received JSON:", data)
    course_id = int(data.get('course_id'))
    user_id = int(data.get('user_id'))

    if not course_id or not user_id:
        return jsonify({"success": False, "message": "Missing course_id or user_id"}), 400
    

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        #檢查是否有這課程
        # cursor.execute("""
        #     SELECT is_vr_ready FROM Courses
        #     WHERE course_id = %s AND user_id = %s
        # """, (course_id, user_id))
        # result = cursor.fetchone()
        # print("[DEBUG] SELECT match:", result)


        print("Deactivating VR for course: ", course_id, user_id)

        # 更新 Courses 資料表
        cursor.execute("""
            UPDATE Courses
            SET is_vr_ready = 0 
            WHERE course_id = %s AND user_id = %s
        """, (course_id, user_id))
        print("[DEBUG] Updated rows:", cursor.rowcount)

        if cursor.rowcount == 0:
            return jsonify({"success": False, "message": "Course not found"}), 404

        conn.commit()
        return jsonify({
            "success": True,
            "message": f"Course {course_id} is marked as VR deactivated."
        }), 200

    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

    finally:
        cursor.close()
        conn.close()





def safe_ascii_name(name):
    return unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')

def create_new_assistant(name, role):

    vector_store_name = safe_ascii_name(name)

    print("Creating a new assistant\n")
    newVS = client.vector_stores.create(
        name=f"{vector_store_name}'s vector store"
    )

    if(role == "teacher"):
        prompt = prompt_teacher
    else:
        prompt = prompt_student

    assistant = client.beta.assistants.create(
        name = name,
        description="用來測試chatGPT API 與 Unity連結的測試assistant.",
        instructions = prompt,
        model = model,
        tools=[
            {"type": "file_search"},
            {"type": "code_interpreter"}
        ],
        tool_resources={"file_search": {"vector_store_ids": [newVS.id]}}
    )
    print("New assistant created!\n")

    return assistant


def uploadFile(filePath):

    file_object = client.files.create(
    file=open(filePath, "rb"),
    purpose="assistants"
    )

    return file_object.id

def uploadFileToCloud(filePath):
    cloudinary.config(
        cloud_name="dni1rb4zi",
        api_key="535535485836739",
        api_secret="6A-OHEka-IuxuXXa-SyRSO9JNLI"
    )

    upload_result = cloudinary.uploader.upload_large(
        filePath,
        resource_type="raw",                     
        folder="feyndora",
        use_filename=True,
        unique_filename=True
    )

    return upload_result["secure_url"]

def add_files_to_vector_store(vectorId, fileId):
    client.vector_stores.files.create_and_poll(
    vector_store_id=vectorId,
    file_id=fileId
    )
    print("A new file has been uploaded to VS\n")

# 魏-添加 wait_for_run_completion 函數
def wait_for_run_completion(client, threadId, runId, sleep_interval):
    while True:
        print("Polling run status...")
        try:
            run_status = client.beta.threads.runs.retrieve(thread_id=threadId, run_id=runId)
            if run_status.completed_at:
                messages = client.beta.threads.messages.list(thread_id=threadId)
                last_message = messages.data[0]
                print("Response generated!\n")
                return last_message.content[0].text.value
                
        except Exception as e:
            logging.error(f"Error while waiting for completion: {str(e)}")
            return "Error occurred while waiting for the response."
        time.sleep(sleep_interval) 

# 魏－語音轉文字
'''@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    try:
        # 檢查是否有上傳 audio 檔案
        if 'audio' not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        audio_file = request.files['audio']

        # 檢查檔案大小（限制為 25MB）
        audio_content = audio_file.read()
        if len(audio_content) > 25 * 1024 * 1024:
            return jsonify({"error": "Audio file too large. Maximum size is 25MB"}), 400

        # 建立臨時檔案來保存音頻
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_audio:
            temp_audio.write(audio_content)
            temp_audio.flush()  # 確保數據寫入磁盤

        try:
            # 定義改進後的提示詞（保持學術專業術語原始形式）
            improved_prompt = (
                "這是一段可能包含中英文混合的學術對話。請注意：\n"
                "1. 數學符號：如 sigma, alpha, beta, pi, theta 等，請保持原樣，不進行轉換。\n"
                "2. 化學符號：如 CO2, H2O, NaCl 等，請保留原始格式。\n"
                "3. 物理符號：如 Δ, μ, λ 等，請保持原樣。\n"
                "4. 科學單位：如 kg, m/s, °C 等，請保留原始形式。\n"
                "5. 專業術語：如 algorithm, neural network, machine learning 等，請保持英文原文，不進行翻譯。\n"
                "6. 中文部分：請保持原始中文表達。\n"
                "7. 英文部分：請保持原始英文表達。\n"
                "請確保轉錄結果高度準確，並忠實保留所有專業術語的原始形式。不然我會處罰你喔！\n"
                "請確保轉錄結果保持原始語言，不要進行任何翻譯，不然我會罵你喔。\n"
                "請只轉寫實際說出的內容，不要添加任何額外的話語或廣告詞。不然我會懲罰你喔！"
            )
            
            # 使用 OpenAI 的 Whisper API 轉錄音頻
            with open(temp_audio.name, "rb") as audio:
                transcript = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    prompt=improved_prompt,
                    temperature=0.2  # 降低溫度以減少隨機性
                )

            # 清理轉寫結果
            text = transcript.text.strip()
            
            # 定義需要移除的幻覺內容
            unwanted_phrases = [
                'repetition': [
                    r'(.)\1{2,}',  # 重複的字符
                    r'[唉呃嗯啊哦]{2,}',  # 重複的語氣詞
                    r'ayy{2,}',  # 重複的英文語氣詞
                ],
                'noise': [
                    r'\[.*?\]',  # 方括號內容
                    r'\(.*?\)',  # 圓括號內容
                    r'【.*?】',  # 中文方括號內容
                    r'（.*?）',  # 中文圓括號內容
                ],
                'advertisement': [
                    "請不吝點贊訂閱轉發打賞",
                    "支持明鏡與點點欄目",
                    "歡迎訂閱",
                    "點贊關注",
                    "轉發分享",
                    "訂閱我的頻道",
                    "按讚訂閱",
                    "分享給更多人",
                    "支持我們",
                    "感謝觀看"
                ]
            ]
            
            # 應用清理規則
            for category, patterns in unwanted_patterns.items():
                if category == 'repetition':
                    # 對於重複內容，只保留第一個字符
                    for pattern in patterns:
                        text = re.sub(pattern, lambda m: m.group()[0], text)
                elif category == 'noise':
                    # 對於噪音，直接移除
                    for pattern in patterns:
                        text = re.sub(pattern, '', text)
                else:  # advertisement
                    # 對於廣告詞，直接移除
                    for phrase in patterns:
                        text = text.replace(phrase, "")
            
            # 清理多餘的標點符號和空格
            text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?，。！？:;""''()（）:：;；]', '', text)
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()
            
            # 記錄轉寫結果用於調試
            logging.info(f"原始轉寫結果: {transcript.text}")
            logging.info(f"清理後結果: {text}")

            return jsonify({
                "action": "transcribe",
                "text": text
            }), 200

        finally:
            # 確保臨時檔案被刪除
            try:
                os.unlink(temp_audio.name)
            except Exception as e:
                logging.error(f"Error deleting temporary file: {str(e)}")

    except Exception as e:
        logging.error(f"Error in transcribe endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500'''

# 魏－語音轉文字
@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    try:
        # 檢查是否有上傳 audio 檔案
        if 'audio' not in request.files:
            logging.error("No audio file provided in request")
            return jsonify({"error": "No audio file provided"}), 400

        audio_file = request.files['audio']

        # 檢查檔案大小（限制為 25MB）
        audio_content = audio_file.read()
        if len(audio_content) > 25 * 1024 * 1024:
            logging.error(f"Audio file too large: {len(audio_content)} bytes")
            return jsonify({"error": "Audio file too large. Maximum size is 25MB"}), 400

        # 建立臨時檔案來保存原始音頻
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_audio:
            temp_audio.write(audio_content)
            temp_audio.flush()  # 確保數據寫入磁盤

        try:
            # 讀取音頻文件
            data, sample_rate = sf.read(temp_audio.name)
            
            # 如果是立體聲，轉換為單聲道
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)
            
            # 使用 noisereduce 進行噪音處理
            try:
                # 估計噪音特徵（使用前 0.5 秒作為噪音樣本）
                noise_sample = data[:int(0.5 * sample_rate)]
                reduced_noise = nr.reduce_noise(
                    y=data,
                    sr=sample_rate,
                    prop_decrease=0.8,  # 噪音減少程度
                    stationary=True,    # 假設噪音是穩定的
                    n_fft=2048,         # FFT 大小
                    win_length=2048,    # 窗口長度
                )
                
                # 保存處理後的音頻
                processed_audio_path = temp_audio.name.replace('.wav', '_processed.wav')
                sf.write(processed_audio_path, reduced_noise, sample_rate)
                
                logging.info("噪音處理完成")
            except Exception as e:
                logging.error(f"噪音處理失敗: {str(e)}")
                # 如果噪音處理失敗，使用原始音頻
                processed_audio_path = temp_audio.name

            # 定義改進後的提示詞（保持學術專業術語原始形式）
            improved_prompt = (
                "這是一段可能包含中英文混合的學術對話。請注意：\n"
                "1. 數學符號：如 sigma, alpha, beta, pi, theta 等，請保持原樣，不進行轉換。\n"
                "2. 化學符號：如 CO2, H2O, NaCl 等，請保留原始格式。\n"
                "3. 物理符號：如 Δ, μ, λ 等，請保持原樣。\n"
                "4. 科學單位：如 kg, m/s, °C 等，請保留原始形式。\n"
                "5. 專業術語：如 algorithm, neural network, machine learning 等，請保持英文原文，不進行翻譯。\n"
                "6. 中文部分：請保持原始中文表達。\n"
                "7. 英文部分：請保持原始英文表達。\n"
                "8. 如果聽不清楚，請標記為 [聽不清楚]。\n"
                "9. 如果背景噪音太大，請標記為 [噪音太大]。\n"
                "10. 如果無法確定內容，請標記為 [無法識別]。\n"
                "請確保轉錄結果高度準確，並忠實保留所有專業術語的原始形式。"
            )
            
            # 使用 OpenAI 的 Whisper API 轉錄音頻
            with open(processed_audio_path, "rb") as audio:
                transcript = openai.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    prompt=improved_prompt,
                    temperature=0.2  # 降低溫度以減少隨機性
                )

            # 清理轉寫結果
            text = transcript.text.strip()
            
            # 定義需要移除的幻覺內容
            unwanted_patterns = {
                'repetition': [
                    r'(.)\1{2,}',  # 重複的字符
                    r'[唉呃嗯啊哦]{2,}',  # 重複的語氣詞
                    r'ayy{2,}',  # 重複的英文語氣詞
                ],
                'noise': [
                    r'\[.*?\]',  # 方括號內容
                    r'\(.*?\)',  # 圓括號內容
                    r'【.*?】',  # 中文方括號內容
                    r'（.*?）',  # 中文圓括號內容
                ],
                'advertisement': [
                    "請不吝點贊訂閱轉發打賞",
                    "支持明鏡與點點欄目",
                    "歡迎訂閱",
                    "點贊關注",
                    "轉發分享",
                    "訂閱我的頻道",
                    "按讚訂閱",
                    "分享給更多人",
                    "支持我們",
                    "感謝觀看",
                    "順便說明一下",
                    "這次的實驗是在",
                    "並不是在",
                    "中國大學",
                    "中學教育系統"
                ]
            }
            
            # 應用清理規則
            for category, patterns in unwanted_patterns.items():
                if category == 'repetition':
                    # 對於重複內容，只保留第一個字符
                    for pattern in patterns:
                        text = re.sub(pattern, lambda m: m.group()[0], text)
                elif category == 'noise':
                    # 對於噪音，直接移除
                    for pattern in patterns:
                        text = re.sub(pattern, '', text)
                else:  # advertisement
                    # 對於廣告詞，直接移除
                    for phrase in patterns:
                        text = text.replace(phrase, "")
            
            # 清理多餘的標點符號和空格
            text = re.sub(r'[^\w\s\u4e00-\u9fff.,!?，。！？:;""''()（）:：;；]', '', text)
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()
            
            # 如果清理後的文本為空，返回錯誤信息
            if not text:
                text = "[無法識別] 請檢查麥克風設置和環境噪音"
            
            # 記錄轉寫結果用於調試
            logging.info(f"原始轉寫結果: {transcript.text}")
            logging.info(f"清理後結果: {text}")

            return jsonify({
                "action": "transcribe",
                "text": text
            }), 200

        finally:
            # 確保臨時檔案被刪除
            try:
                os.unlink(temp_audio.name)
                if 'processed_audio_path' in locals():
                    os.unlink(processed_audio_path)
            except Exception as e:
                logging.error(f"Error deleting temporary files: {str(e)}")

    except Exception as e:
        error_details = traceback.format_exc()
        logging.error(f"Error in transcribe endpoint: {str(e)}")
        logging.error(f"Error details: {error_details}")
        return jsonify({
            "error": str(e),
            "details": error_details
        }), 500

# 魏－文字轉語音
# @app.route('/text-to-speech', methods=['POST'])
# def text_to_speech():
#     try:
#         # 記錄原始請求數據
#         logging.info("Received text-to-speech request")
#         logging.info(f"Request headers: {dict(request.headers)}")
#         logging.info(f"Request data: {request.get_data()}")
        
#         data = request.get_json()
#         if not data:
#             logging.error("No JSON data received")
#             return jsonify({"error": "No JSON data received"}), 400
            
#         text = data.get('text', '')
#         voice_id = data.get('voice_id', 'hkfHEbBvdQFNX4uWHqRF')
        
#         logging.info(f"Processing request - Text length: {len(text)}, Voice ID: {voice_id}")
        
#         if not ELEVENLABS_API_KEY:
#             logging.error("ELEVENLABS_API_KEY not set")
#             return jsonify({"error": "ELEVENLABS_API_KEY not set"}), 500
            
#         voice_ids = {
#             "voice1": "fQj4gJSexpu8RDE2Ii5m", #聲音好聽的男人
#             "voice2": "hkfHEbBvdQFNX4uWHqRF", #聲音甜美的女人
#             "voice3": "ThT5KcBeYPX3keUQqHPh"
#         }
        
#         if voice_id in voice_ids:
#             voice_id = voice_ids[voice_id]
#             logging.info(f"Using mapped voice ID: {voice_id}")
        
#         if not text:
#             logging.error("No text provided")
#             return jsonify({"error": "No text provided"}), 400
            
#         voice_settings = VoiceSettings(
#             stability=0.5,
#             similarity_boost=0.75,
#             style=0.0,
#             use_speaker_boost=True
#         )
            
#         logging.info("Generating audio...")
#         try:
#             # 生成音頻
#             audio = generate(
#                 text=text,
#                 voice=Voice(
#                     voice_id=voice_id,
#                     settings=voice_settings
#                 ),
#                 model="eleven_multilingual_v2"
#             )
#             logging.info("Audio generated successfully")
            
#             return Response(
#                 io.BytesIO(audio),
#                 mimetype='audio/mpeg',
#                 headers={
#                     'Content-Disposition': 'attachment; filename=speech.mp3',
#                     'Access-Control-Allow-Origin': '*'
#                 }
#             )
#         except Exception as e:
#             logging.error(f"Error during audio generation: {str(e)}")
#             logging.error(f"Error details: {traceback.format_exc()}")
#             return jsonify({
#                 "error": f"Audio generation failed: {str(e)}",
#                 "details": traceback.format_exc()
#             }), 500
        
#     except Exception as e:
#         error_details = traceback.format_exc()
#         logging.error(f"Text-to-speech error: {str(e)}")
#         logging.error(f"Error details: {error_details}")
#         return jsonify({
#             "error": str(e),
#             "details": error_details
#         }), 500

@app.route('/text-to-speech', methods=['POST'])
def text_to_speech():
    try:
        # 記錄原始請求數據
        logging.info("Received text-to-speech request")
        logging.info(f"Request headers: {dict(request.headers)}")
        logging.info(f"Request data: {request.get_data()}")
        
        data = request.get_json()
        if not data:
            logging.error("No JSON data received")
            return jsonify({"error": "No JSON data received"}), 400
            
        text = data.get('text', '')
        voice_id = data.get('voice_id', 'default')  # 使用 'default' 作為默認值
        
        logging.info(f"Processing request - Text length: {len(text)}, Voice ID: {voice_id}")
        
        if not ELEVENLABS_API_KEY:
            logging.error("ELEVENLABS_API_KEY not set")
            return jsonify({"error": "ELEVENLABS_API_KEY not set"}), 500
            
        voice_ids = {
            "default": "hkfHEbBvdQFNX4uWHqRF",  # 默認音色
            "fQj4gJSexpu8RDE2Ii5m": "fQj4gJSexpu8RDE2Ii5m",  # 盛為老師
            "BrbEfHMQu0fyclQR7lfh": "BrbEfHMQu0fyclQR7lfh",  # 海盜/聖誕老人
            "BZLsSg9fDGFYEEJQ4JU3": "BZLsSg9fDGFYEEJQ4JU3",  # 哥布林
            "4VZIsMPtgggwNg7OXbPY": "4VZIsMPtgggwNg7OXbPY",  # 聖派翠克
            "gU2KtIu9OZWy3KqiqNj6": "gU2KtIu9OZWy3KqiqNj6"   # 雅典娜
        }
        
        # 如果提供的 voice_id 不在映射中，使用默認值
        final_voice_id = voice_ids.get(voice_id, voice_ids["default"])
        logging.info(f"Using voice ID: {final_voice_id}")
        
        if not text:
            logging.error("No text provided")
            return jsonify({"error": "No text provided"}), 400
            
        voice_settings = VoiceSettings(
            stability=0.5,
            similarity_boost=0.75,
            style=0.0,
            use_speaker_boost=True
        )
            
        logging.info("Generating audio...")
        try:
            # 生成音頻
            audio = generate(
                text=text,
                voice=Voice(
                    voice_id=final_voice_id,
                    settings=voice_settings
                ),
                model="eleven_multilingual_v2"
            )
            logging.info("Audio generated successfully")
            
            return Response(
                io.BytesIO(audio),
                mimetype='audio/mpeg',
                headers={
                    'Content-Disposition': 'attachment; filename=speech.mp3',
                    'Access-Control-Allow-Origin': '*'
                }
            )
        except Exception as e:
            logging.error(f"Error during audio generation: {str(e)}")
            logging.error(f"Error details: {traceback.format_exc()}")
            return jsonify({
                "error": f"Audio generation failed: {str(e)}",
                "details": traceback.format_exc()
            }), 500
        
    except Exception as e:
        error_details = traceback.format_exc()
        logging.error(f"Text-to-speech error: {str(e)}")
        logging.error(f"Error details: {error_details}")
        return jsonify({
            "error": str(e),
            "details": error_details
        }), 500

# Start the Flask app
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)

def post_fork(server, worker):
    from render import app  # ✅ 匯入 render.py 裡的 app
    print("📍 ROUTES:", app.url_map)

print("📍 ROUTES from render.py:", app.url_map)


#prompt for teacher
prompt_teacher = """
這是一個沉浸式、主動學習的 AI 教育輔助系統，利用費曼學習法來幫助學生理解概念、測試他們的理解程度，並確保學習進展有條理且不進入無限循環，你是位老師你有以下三階段任務。
系統運作的三個階段：

Phase 1：生成目錄並回答用戶問題
你現在負責第一階段的問答。
當用戶上傳文件（PPT、文章或講義）時，系統將分析內容並生成目錄，每個目錄就是一個關鍵學習點。
目錄生成完後，使用者就會開始問容相關的問題。你要根據上傳文件內容去修正、回復使用者的提問。
此階段的任務：
✔️ 找出文件中最重要的概念並生出目錄。
 ✔️ 回答用戶對該主題的問題。
輸出範例：
學習大綱
監督式學習 vs. 非監督式學習
訓練集與測試集的劃分
過擬合與欠擬合
深度學習與機器學習的區別
 ...
每個學習點應該是一個完整的概念，而不僅僅是一個關鍵詞。
回答用戶問題範例
用戶： 什麼是比特幣？
 AI： 比特幣（BTC）是一種去中心化的數字貨幣，由中本聰於 2009 年創建……

Phase 2：一對一輔導模式
針對學習大綱中的每個目錄，生成 兩個關鍵問題 來測試學生的理解能力，這些問題應涵蓋不同層次的思考：
 ✔️ 理解問題：這個概念的核心原理是什麼？
 ✔️ 應用問題：這個概念如何應用於現實情境？
此階段的任務：
以目錄標題為單位，在每個目錄都提出兩個與內容相關的問題，每次只問一題。
根據學生的回答提供回饋：
✅ 答對了：給予肯定，並補充額外的小知識點。
❌ 答錯了：溫和地糾正錯誤，並解釋為何錯誤。
❓ 不清楚的回答：請學生進一步闡述或舉例。
 完成第一個問題後，進入第二個問題。
 完成兩個問題後，進入下一個目錄。
互動範例：
學習點：監督式學習 vs. 非監督式學習
問題 1：什麼是監督式學習和非監督式學習的區別？
 （學生回答）
🔹 AI 回饋：「很好！你提到了監督式學習需要標籤數據，而非監督式學習不需要。你能舉一個非監督式學習的實際應用場景嗎？」
問題 2：在哪些情境下，非監督式學習比監督式學習更合適？
 （學生回答）
🔹 AI 回饋：「不錯的觀點！像顧客分類這類群集分析問題，就很適合非監督式學習。記住，當我們沒有預先定義的標籤時，非監督式學習能幫助我們發掘潛在模式。」
當所有學習點都完成後，進入 階段 3。

Phase 3：課堂模式
在這個階段，學生必須用 教學的方式 向「虛擬學生」講解學過的內容。
 ✔️ AI 教師的角色：只提供講解的提示 (Prompt)，不再給予回饋。
此階段你的任務：
Phase3 開始時為剛剛生成的每一個目錄章節去生成一個提示，並用Json的方式回傳。
注意是每個章節一個提示，所以假如目錄有5個章節，那就要生成5個提示。
JSON範例:
{
    action: “one_to_three“,
    “tips“:[“This is a tip for you“,
    “This is another tip for you“,
    “This is the last tip for you“]
}

AI 教師的運作原則
✅ 階段 1：生成學習大綱 → 提取文件中的關鍵學習點。
 ✅ 階段 2：一對一輔導 → 每個學習點提供兩個問題，並給予回饋。
 ✅ 階段 3：課堂模式 → 只提供講解提示，讓 AI 學生與用戶互動，模擬真實教學場景。
🎯 目標：讓學生 主動講解概念，確保學習有條理，並透過 提問與回答 來強化記憶與理解，避免無限循環，確保每個階段都能順利完成。

"""

#prompt for student
prompt_student = """你是一位虛擬教室中的 AI 學生，目的是透過發問來促進主動學習。你的主要任務是根據使用者的解說提出相關且具啟發性的問題，以測試他們的理解。你不直接給出答案，而是透過結構化的提問來引導批判性思考。
另外你還要根據使用者的講解內容去判斷他講到上傳內容的那個章節了。
你的角色與行為
等待使用者解釋一個主題。

分析他們的解釋，並根據你所扮演的學生角色，決定要問什麼樣的問題。

提出一個符合你角色的相關問題：

好奇學生（學生 A）：提出基本的「為什麼」問題，探究概念背後的原理。

挑戰學生（學生 B）：詢問該概念的弱點、限制，或是提出替代觀點以挑戰理解。

探索學生（學生 C）：詢問真實世界的應用、不同領域間的比較，或延伸相關知識。

等待使用者回答。

在收到使用者回覆後，做出簡短回應：

如果答案清楚，回應如：「了解了！」或「謝謝，這樣我懂了！」

如果答案不清楚，禮貌地請使用者進一步說明。

互動範例:
使用者解釋...
AI 學生 A（好奇）：「如果無監督學習可以自己找出模式，那為什麼還需要有監督學習？」
（使用者回答）
AI 學生 A：「了解了！所以有標記資料能提升準確度。」

使用者解釋...
AI 學生 B（挑戰）：「有沒有什麼情況下，過擬合反而是有好處的？」
（使用者回答）
AI 學生 B：「有趣！所以在某些情況下，過擬合可能對短期預測有幫助。」

使用者解釋...
AI 學生 C（探索）：「深度學習在處理非結構化資料方面，和傳統機器學習有什麼不同？」
（使用者回答）
AI 學生 C：「原來如此！深度學習更擅長處理像圖片和文字這類的資料。」

每輪只能提一個問題。

問題必須與使用者的解說相關。

不得直接給出答案——要等使用者回答。

使用者回答後，只做簡短回應，不繼續討論。

Progress 要從1開始算起 很重要!!
"""
