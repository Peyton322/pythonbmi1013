import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import app, bmi_guidance, open_database
from contextlib import closing


class BmiAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = patch.dict(app.config, DATABASE=str(Path(self.directory.name) / "test.sqlite3"), TESTING=True)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = app.test_client()

    def calculate(self, name, weight="65"):
        return self.client.post("/", data={"name": name, "height": "170", "weight": weight}, follow_redirects=True)

    def test_empty_user_list(self):
        response = self.client.get("/users")
        self.assertEqual(response.status_code, 200)
        self.assertIn("目前還沒有使用者紀錄", response.get_data(as_text=True))

    def test_named_calculation_saves_and_links_history(self):
        timestamp = datetime(2026, 10, 20, 6, 30, 5, tzinfo=timezone.utc)
        with patch("app.datetime") as clock:
            clock.now.return_value = timestamp
            response = self.calculate("小明")
        self.assertIn("已儲存，查看 小明 的歷史紀錄", response.get_data(as_text=True))
        listing = self.client.get("/users").get_data(as_text=True)
        self.assertIn("小明", listing)
        self.assertIn('href="/users/1"', listing)
        page = self.client.get("/users/1").get_data(as_text=True)
        self.assertIn("22.5", page)
        self.assertIn("2026/10/20 14:30:05", page)

    def test_same_name_combines_records_and_other_users_are_separate(self):
        self.calculate(" 小明 ", "65")
        self.calculate("小華", "75")
        self.calculate("小明", "50")
        page = self.client.get("/users/1").get_data(as_text=True)
        self.assertIn("共 2 筆", page)
        self.assertLess(page.index("17.3"), page.index("22.5"))
        self.assertNotIn("26.0", page)
        self.assertIn('bmi-value bmi-alert', page)
        self.assertIn("26.0", self.client.get("/users/2").get_data(as_text=True))
        with closing(open_database()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)

    def test_refresh_saved_result_does_not_duplicate_record(self):
        response = self.client.post("/", data={"name": "小明", "height": "170", "weight": "65"})
        self.assertEqual(response.status_code, 303)
        self.client.get(response.location)
        self.client.get(response.location)
        with closing(open_database()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM bmi_records").fetchone()[0], 1)

    def test_invalid_or_anonymous_calculation_does_not_save(self):
        self.client.post("/", data={"name": "小明", "height": "0", "weight": "65"})
        self.calculate("   ")
        response = self.calculate("名" * 81)
        self.assertIn("姓名請勿超過 80 個字", response.get_data(as_text=True))
        self.assertIn("目前還沒有使用者紀錄", self.client.get("/users").get_data(as_text=True))

    def test_name_is_escaped_and_sql_characters_are_stored_literally(self):
        name = "<script>alert('x')</script>"
        self.calculate(name)
        self.calculate("Robert'); DROP TABLE users;--")
        for path in ["/users", "/users/1", "/?record=1"]:
            page = self.client.get(path).get_data(as_text=True)
            self.assertNotIn("<script>", page)
            self.assertIn("&lt;script&gt;", page)
        with closing(open_database()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)

    def test_missing_user_and_record_return_404(self):
        for path in ["/users/999", "/?record=999", "/?record=invalid"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_records_persist_between_clients(self):
        self.calculate("小明")
        another_client = app.test_client()
        self.assertIn("22.5", another_client.get("/users/1").get_data(as_text=True))

    def test_initial_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("了解自己的<br><em>健康狀況。</em>", page)
        self.assertIn("計算你的 BMI", page)

    def test_calculation_and_advice(self):
        response = self.client.post("/", data={"height": "170", "weight": "65"})
        page = response.get_data(as_text=True)
        self.assertIn("22.5", page)
        self.assertIn("健康體位", page)
        self.assertIn("維持均衡飲食", page)

    def test_taiwan_adult_thresholds(self):
        for bmi, category in [
            (18.4, "體重過輕"),
            (18.5, "健康體位"),
            (23.9, "健康體位"),
            (24.0, "體重過重"),
            (26.9, "體重過重"),
            (27.0, "肥胖"),
        ]:
            with self.subTest(bmi=bmi):
                self.assertEqual(bmi_guidance(bmi)["label"], category)

    def test_invalid_fields_do_not_produce_result(self):
        for height, weight in [("", "65"), ("0", "65"), ("abc", "65"), ("170", "-2"), ("inf", "65"), ("170", "nan"), ("1e-300", "65"), ("1e308", "65"), ("1", "1e308")]:
            with self.subTest(height=height, weight=weight):
                response = self.client.post("/", data={"height": height, "weight": weight})
                page = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn('aria-invalid="true"', page)
                self.assertNotIn("YOUR RESULT", page)

    def test_input_is_escaped(self):
        response = self.client.post("/", data={"height": '<script>alert(1)</script>', "weight": "65"})
        page = response.get_data(as_text=True)
        self.assertNotIn("<script>", page)
        self.assertIn("請輸入大於 0", page)


if __name__ == "__main__":
    unittest.main()
