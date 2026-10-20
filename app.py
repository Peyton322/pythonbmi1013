import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, url_for

app = Flask(__name__)

# Keep Azure data outside the deployment package and separate each slot's history.
if os.environ.get("WEBSITE_SITE_NAME") and os.environ.get("HOME"):
    data_directory = Path(os.environ["HOME"]) / "data" / "bmi" / os.environ.get("WEBSITE_SLOT_NAME", "production")
else:
    data_directory = Path(app.instance_path)
app.config["DATABASE"] = os.environ.get("BMI_DATABASE_PATH", str(data_directory / "history.sqlite3"))


def open_database():
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(app.config["DATABASE"], timeout=10)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    with database:
        database.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
        """)
        database.execute("""
            CREATE TABLE IF NOT EXISTS bmi_records (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                height REAL NOT NULL,
                weight REAL NOT NULL,
                bmi REAL NOT NULL,
                calculated_at TEXT NOT NULL
            )
        """)
        database.execute("CREATE INDEX IF NOT EXISTS records_by_user ON bmi_records(user_id, id DESC)")
    return database


@app.template_filter("taipei_time")
def taipei_time(value):
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).strftime("%Y/%m/%d %H:%M:%S")


def save_record(name, height, weight, bmi):
    with closing(open_database()) as database, database:
        database.execute("INSERT OR IGNORE INTO users(name) VALUES (?)", (name,))
        user = database.execute("SELECT id FROM users WHERE name = ?", (name,)).fetchone()
        record = database.execute(
            "INSERT INTO bmi_records(user_id, height, weight, bmi, calculated_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], height, weight, bmi, datetime.now(timezone.utc).isoformat()),
        )
        return record.lastrowid


@app.get("/users")
def users():
    with closing(open_database()) as database:
        all_users = database.execute("""
            SELECT users.id, users.name, COUNT(bmi_records.id) AS record_count,
                   MAX(bmi_records.calculated_at) AS latest_at
            FROM users JOIN bmi_records ON users.id = bmi_records.user_id
            GROUP BY users.id ORDER BY users.name, users.id
        """).fetchall()
    return render_template("users.html", users=all_users, selected_user=None)


@app.get("/users/<int:user_id>")
def user_history(user_id):
    with closing(open_database()) as database:
        user = database.execute("SELECT id, name FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            abort(404)
        records = database.execute(
            "SELECT * FROM bmi_records WHERE user_id = ? ORDER BY id DESC", (user_id,)
        ).fetchall()
    return render_template("users.html", selected_user=user, records=records)


def bmi_guidance(bmi):
    if bmi < 18.5:
        return {
            "label": "體重過輕",
            "tone": "low",
            "advice": "留意是否攝取足夠且均衡的營養，規律進食並搭配適度肌力活動；若體重持續下降，建議諮詢醫師或營養師。",
        }
    if bmi < 24:
        return {
            "label": "健康體位",
            "tone": "healthy",
            "advice": "維持均衡飲食與規律運動，並持續留意睡眠及生活習慣，幫助保持健康體位。",
        }
    if bmi < 27:
        return {
            "label": "體重過重",
            "tone": "high",
            "advice": "可從減少含糖飲料、增加蔬菜與日常活動量開始，循序建立適合自己的健康習慣。",
        }
    return {
        "label": "肥胖",
        "tone": "high",
        "advice": "建議與醫師或營養師討論適合自己的飲食及運動計畫，並留意血壓、血糖等健康指標。",
    }


def parse_positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


@app.route("/", methods=["GET", "POST"])
def index():
    name_input = ""
    height_input = ""
    weight_input = ""
    errors = {}
    result = None

    if request.method == "GET" and "record" in request.args:
        record_id = request.args.get("record", type=int)
        with closing(open_database()) as database:
            record = database.execute("""
                SELECT bmi_records.*, users.name FROM bmi_records
                JOIN users ON users.id = bmi_records.user_id WHERE bmi_records.id = ?
            """, (record_id,)).fetchone()
        if record is None:
            abort(404)
        name_input = record["name"]
        height_input = f"{record['height']:g}"
        weight_input = f"{record['weight']:g}"
        result = {"bmi": f"{record['bmi']:.1f}", "user_id": record["user_id"], **bmi_guidance(record["bmi"])}

    if request.method == "POST":
        name_input = request.form.get("name", "").strip()
        height_input = request.form.get("height", "").strip()
        weight_input = request.form.get("weight", "").strip()
        height = parse_positive_number(height_input)
        weight = parse_positive_number(weight_input)

        if len(name_input) > 80:
            errors["name"] = "姓名請勿超過 80 個字。"

        if height is None:
            errors["height"] = "請輸入大於 0 的有效身高（公分）。"
        if weight is None:
            errors["weight"] = "請輸入大於 0 的有效體重（公斤）。"

        if not errors:
            height_meters = height / 100
            height_squared = height_meters * height_meters
            if not math.isfinite(height_squared) or height_squared == 0:
                errors["height"] = "無法使用這組數值計算 BMI，請檢查身高與體重。"
            else:
                bmi = weight / height_squared
                if not math.isfinite(bmi) or bmi == 0:
                    errors["weight"] = "無法使用這組數值計算 BMI，請檢查身高與體重。"
                else:
                    displayed_bmi = round(bmi, 1)
                    if name_input:
                        record_id = save_record(name_input, height, weight, displayed_bmi)
                        return redirect(url_for("index", record=record_id), code=303)
                    result = {"bmi": f"{displayed_bmi:.1f}", **bmi_guidance(displayed_bmi)}

    return render_template(
        "index.html",
        name_input=name_input,
        height_input=height_input,
        weight_input=weight_input,
        errors=errors,
        result=result,
    )


if __name__ == "__main__":
    app.run(debug=True)
