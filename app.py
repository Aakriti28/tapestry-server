import boto3
from flask import Flask, request, json, jsonify, g
from functools import wraps
import lmdb
import logging
import numpy as np
import orjson
import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import Json
import secrets
import sys
import time

import grid

EXPT_DIR="./compute/"
sys.path.append(EXPT_DIR)
import config
config.root_dir=EXPT_DIR
import get_test_results as expt

"""
    App setup, teardown and constants
"""

app = Flask(__name__)
app.secret_key = 'covid-19-testing-backend'
psycopg2.extras.register_default_jsonb(loads=orjson.loads, globally=True)

# Response headers
CONTENT_TYPE = "Content-Type"
CONTENT_JSON = "application/json"

# Using lmdb as a simple K/V store for storing auth tokens and OTP for mobile numbers. Can be replaced by redis once requirements get more complex
# Max lmdb size
LMDB_SIZE = 16 * 1024 * 1024
LMDB_PATH = './workdir/db'
lmdb_write_env = lmdb.open(LMDB_PATH, map_size=LMDB_SIZE)
lmdb_read_env = lmdb.open(LMDB_PATH, readonly=True)

# Matrices
MLABELS = expt.get_matrix_sizes_and_labels()
MATRICES = expt.get_matrix_labels_and_matrices()
VECTOR_SIZES = [int(k.split("x")[0]) for k in MLABELS]
BATCH_SIZES = {k : f'{k.split("x")[1]} Samples ( {k.split("x")[0]} Tests)' for k in MLABELS}
GRID_JSON, CELL_JSON = grid.generate_grid_and_cell_data_json(MLABELS, MATRICES)
BATCH_JSON = orjson.dumps({"data" : BATCH_SIZES})

# App Version
MIN_VERSION = "1.0"
MIN_VERSION_INTS = tuple(int(x) for x in MIN_VERSION.split("."))
APP_UPDATE_URL = "https://play.google.com/store/apps/details?id=com.o1"

DUMMY_OTP = '3456'
AUTH_TOKEN_VALIDITY = 90 * 24 * 60 * 60 # 90 days validity of auth token
OTP_VALIDITY = 900
# pg connection pool
pgpool = psycopg2.pool.SimpleConnectionPool(1, 4, user = "covid", password = "covid", host = "127.0.0.1", port = "5432", database = "covid")

# Alerts on test upload and failure
NOTIFY_EMAILS = ['ssgosh@gmail.com', 'manoj.gopalkrishnan@gmail.com']
TEST_ARN = 'arn:aws:sns:ap-south-1:691823188847:c19-test'
PROD_ARN = 'arn:aws:sns:ap-south-1:691823188847:C19-PROD'
SNS_CLIENT = boto3.client('sns')
NOTIFICATIONS_ENABLED = False

"""
    Utils
"""

def curr_epoch():
    return int(time.time())

def err_json(msg):
    return jsonify(error=msg),500

def verify_batch_dimensions(b, l):
    return int(b.split("x")[0]) == l

def app_version_check(version):
    if version is None or version == "" or version.isspace() or version.count(".") != 1:
        return False
    vs = tuple(int(x) for x in version.split("."))
    return vs >= MIN_VERSION_INTS

@app.errorhandler
def error_handler(error):
    app.logger.error("Error occured" + str(error))
    return err_json("Unhandled error!!")

def normalize_phone(phone):
    if phone is None or phone == "" or phone.isspace():
        return None
    phone = phone.strip()
    if phone.startswith('+91') and len(phone) == 13:
        return phone
    if len(phone) == 11 and phone.startswith('0') and phone.isdigit():
        return '+91' + phone[1:]
    if len(phone) == 10 and phone.isdigit() and not phone.startswith('0'):
        return '+91' + phone
    return None

def normalize_email(email):
    if email is None or email == "" or email.isspace() or email.count("@") != 1 or email.count(":") != 0:
        return None
    esp = email.split("@")
    if esp[1] == "" or esp[1].count(".") == 0:
        return None
    return email.strip()

def parse_lmdb_otp_data(raw_data):
    # otp:current time
    return raw_data.decode('utf8').split(':')

def parse_lmdb_auth_data(raw_data):
    # user_id:auth_token:timestamp
    return raw_data.decode('utf8').split(':')

def check_auth(request):
    "Checks if user is signed in using auth header"
    headers = request.headers
    auth_token = headers.get('X-Auth', "")
    mob = headers.get('X-Mob', "")
    reg_phone = normalize_phone(mob)
    app.logger.info(f'Mob : {reg_phone}  Token: {auth_token}')
    if auth_token is None or auth_token == '' or reg_phone is None:
        return False
    raw_data = None
    with lmdb_read_env.begin() as txn:
        raw_data = txn.get(reg_phone.encode('utf8'))
    if raw_data is None:
        return False
    data = parse_lmdb_auth_data(raw_data)
    saved_token = data[1]
    if saved_token == auth_token and curr_epoch() - int(data[2]) < AUTH_TOKEN_VALIDITY:
        g.user_id = int(data[0])
        return True
    return False

def requires_auth(func):
    "Function for basic authentication check"
    @wraps(func)
    def decorated(*args, **kwargs):
        "Decorator function for auth"
        if not check_auth(request):
            return err_json("Invalid credentials")
        return func(*args, **kwargs)
    return decorated

def select(query, params):
    try:
        conn = pgpool.getconn()
        with conn.cursor() as cur:
            app.logger.info(f"Executing query: {query} with params {params}")
            cur.execute(query, params)
            return cur.fetchall()
    except:
        raise
    finally:
        pgpool.putconn(conn)

def execute_sql(query, params, one_row=False):
    try:
        conn = pgpool.getconn()
        with conn.cursor() as cur:
            app.logger.info(f"Executing query: {query} with params {params}")
            cur.execute(query, params)
            conn.commit()
            if one_row:
                return cur.fetchone()
            return cur.fetchall()
    except:
        raise
    finally:
        pgpool.putconn(conn)

def publish_message(topic, message, subject=None):
    if not NOTIFICATIONS_ENABLED:
        return
    SNS_CLIENT.publish(TopicArn=topic, Message=message, Subject=subject)

def process_test_upload(test_id, batch, vector):
    try:
        return expt.get_test_results(MLABELS[batch], np.float32(vector))
    except Exception as e:
        app.logger.error("Error occured" + str(e))
        return {"error" : str(e)}

def notify_test_success(test_id, batch, mresults):
    succ_msg = f"""
    Test ID: {test_id} successful at {time.ctime()}
    Batch size: {batch}
    Matrix used: {MLABELS[batch]}
    Result summary:
    {mresults["result_string"]}
    """
    publish_message(PROD_ARN, succ_msg, "Test upload success")

def notify_test_failure(test_id, batch, mresults):
    err_msg = f"""
    Test ID: {test_id} failed at {time.ctime()}
    Batch size: {batch}
    Matrix used: {MLABELS[batch]}
    Error summary:
    {mresults["error"]}
    """
    publish_message(PROD_ARN, err_msg, "Test upload failure")

def post_process_results(test_id, batch, mresults):
    if "error" in mresults:
        notify_test_failure(test_id, batch, mresults)
        return err_json("Error occured while processing test upload. Don't worry! We will try again soon!")
    if "x" in mresults:
        mresults["x"] = mresults["x"].tolist()
    app.logger.info(mresults["result_string"])
    test_results_sql = """insert into test_results (test_id, matrix_label, result_data ) values (%s, %s, %s) on conflict(test_id) 
    do update set updated_at = now(), matrix_label=excluded.matrix_label, result_data=excluded.result_data returning test_id;"""
    execute_sql(test_results_sql, (test_id, MLABELS[batch], Json(mresults, dumps=orjson.dumps)))
    notify_test_success(test_id, batch, mresults)
    return jsonify(test_id=str(test_id), results=mresults["result_string"])

"""
    Endpoints here
"""

@app.route('/ping', methods=['GET'])
def ping():
    return "PONG"

@app.route('/app_version_check', methods=['GET'])
def app_version_check_endpoint():
    app_version = request.args.get('version')
    force = not app_version_check(app_version)
    return jsonify(force=force, url=APP_UPDATE_URL)

@app.route('/request_otp', methods=['POST'])
def request_otp():
    # TODO : generate OTP, send SMS using Exotel
    payload = request.json
    app.logger.info(payload)
    reg_phone = normalize_phone(payload.get('phone', None))
    if reg_phone is None:
        return err_json("Invalid mobile number")
    otp_key = 'otp:' + reg_phone
    otp_value = DUMMY_OTP + ':' + str(curr_epoch())
    with lmdb_write_env.begin(write=True) as txn:
        txn.put(otp_key.encode('utf8'), otp_value.encode('utf8'))
    return jsonify(phone=reg_phone)

@app.route('/validate_otp', methods=['POST'])
def validate_otp():
    payload = request.json
    otp = payload['otp']
    reg_phone = normalize_phone(payload.get('phone', None))
    if reg_phone is None or otp is None or not otp.isdigit():
        return err_json("Mobile or OTP incorrect")
    otp_key = 'otp:' + reg_phone
    raw_data = None
    with lmdb_read_env.begin() as txn:
        raw_data = txn.get(otp_key.encode('utf8'))
    if raw_data is None:
        return err_json("Invalid mobile number")
    data = parse_lmdb_otp_data(raw_data)
    curr_time = curr_epoch()
    if data[0] != otp or curr_time - int(data[1]) > 900:
        return err_json("Invalid or expired OTP")
    token = secrets.token_urlsafe(16)
    upsert_sql = "insert into users(phone) values (%s) on conflict(phone) do update set phone=excluded.phone returning id;"
    user_id = execute_sql(upsert_sql, (reg_phone,), one_row=True)[0]
    auth_value = str(user_id) + ":" + token + ":" + str(curr_time)
    with lmdb_write_env.begin(write=True) as txn:
        txn.put(reg_phone.encode('utf8'), auth_value.encode('utf8'))
    return jsonify(user_id=user_id, token=token, phone=reg_phone)

@app.route('/dashboard', methods=['GET'])
@requires_auth
def user_dashboard():
    pagination = request.args.get('pagination', '')
    app.logger.info(f'Pagination : {pagination}')
    pagination_clause = ' and u.id < %s'
    if pagination is None or not pagination or pagination == '' or pagination == 'false':
        pagination_clause = ''
        pagination = 0
    dashboard_sql = f"""select u.id as test_id, u.updated_at, r.test_id, u.test_data, u.label, u.batch_size  
    from test_uploads u left join test_results r on u.id = r.test_id where u.user_id = %s {pagination_clause} order by u.id desc limit 50;"""
    params = (g.user_id,) if pagination == 0 else (g.user_id, int(pagination))
    res = select(dashboard_sql, params)
    last_pag = False
    if not res or len(res) == 0:
        return jsonify(data=[], pagination=last_pag)
    results = [{"test_id" : r[0], "updated_at" : r[1], "results_available" : r[2] != None, "test_data": r[3], "label" : r[4], "batch" : r[5]} for r in res]
    if len(results) >= 50:
        last_pag = str(results[-1]["test_id"])
    return jsonify(data=results, pagination=last_pag)

@app.route('/start_test', methods=['POST'])
@requires_auth
def start_test():
    payload_json = request.json
    batch = payload_json.get('batch', "").strip()
    label = payload_json.get('label', "").strip()
    if label == "" or label.isspace() or batch == "" or batch.isspace() or batch not in MLABELS:
        return err_json(f"Empty test label or invalid batch size {batch}")
    test_uploads_sql = "insert into test_uploads (user_id, label, batch_size) values (%s, %s, %s) on conflict(user_id, label) do nothing returning id;"
    res = execute_sql(test_uploads_sql, (g.user_id, label, batch))
    if not res or len(res) == 0:
        return err_json(f"Label '{label}' already exists.")
    test_id = res[0][0]
    return jsonify(test_id=str(test_id))

@app.route('/test_data', methods=['POST', 'PUT'])
@requires_auth
def upload_test_data():
    payload_json = request.json
    test_id = int(payload_json['test_id'])
    test_data = payload_json.get('test_data', [])
    batch = payload_json.get('batch', "").strip()
    if batch == "" or batch.isspace() or batch not in MLABELS:
        return err_json(f"Invalid batch size : {batch}")
    lp = len(test_data)
    if not verify_batch_dimensions(batch, lp) or lp not in VECTOR_SIZES:
        err_msg = f"Invalid CT vector size of {lp} for batch type {batch}"
        app.logger.error(err_msg)
        return err_json(err_msg)
    test_uploads_sql ="update test_uploads set batch_end_time = now(), updated_at = now(), test_data = %s where id = %s and user_id = %s returning id;"
    res = execute_sql(test_uploads_sql, (test_data, test_id, g.user_id))
    if not res or len(res) == 0:
        return err_json(f"Test id not found {test_id}")
    updated_id = res[0][0]
    mresults = process_test_upload(test_id, batch, test_data)
    return post_process_results(test_id, batch, mresults)

@app.route('/results/<test_id>', methods=['GET'])
@requires_auth
def fetch_test_results(test_id):
    test_id = int(test_id)
    result_sql = "select r.test_id, r.result_data, r.matrix_label, u.batch_size, u.label from test_results r, test_uploads u where r.test_id = u.id and u.user_id = %s and u.id = %s"
    res = select(result_sql, (g.user_id, test_id))
    if not res or len(res) == 0:
        return err_json(f"Test not found for test_id : {test_id}")
    result = res[0]
    app.logger.info(f'Result: {result}')
    return jsonify(test_id=test_id, result=result[1]["result_string"], matrix=result[2], batch=result[3], label=result[4])

@app.route('/batch_data', methods=['GET'])
def batch_data():
    return BATCH_JSON, 200, {CONTENT_TYPE : CONTENT_JSON}

@app.route('/grid_data/<batch_size>', methods=['GET'])
def screen_data(batch_size):
    return GRID_JSON.get(batch_size.strip(), "{}"), 200, {CONTENT_TYPE : CONTENT_JSON}

@app.route('/cell_data/<batch_size>', methods=['GET'])
def cell_data(batch_size):
    return CELL_JSON.get(batch_size.strip(), "{}"), 200, {CONTENT_TYPE : CONTENT_JSON}

"""
    Main
"""
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)
    NOTIFICATIONS_ENABLED = True

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)