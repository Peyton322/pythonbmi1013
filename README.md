# BMI 計算器

使用 Flask 製作的成人 BMI 網頁計算器。輸入身高（公分）和體重（公斤）後，頁面會顯示 BMI（小數點後一位）、體位分類與生活建議。

## 啟動

需安裝 Python 3.9 以上版本。在專案資料夾執行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

接著開啟 http://127.0.0.1:5000/ 。若 PowerShell 不允許啟用虛擬環境，也可以使用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` 和 `.\.venv\Scripts\python.exe app.py`。

## 計算方式

BMI = 體重（公斤）÷ 身高（公尺）²。分類採臺灣成人體位參考標準：低於 18.5 為體重過輕、18.5 至未滿 24 為健康體位、24 至未滿 27 為體重過重、27 以上為肥胖。頁面以顯示至小數點後一位的 BMI 進行分類。

這只是成人體位參考，不能取代專業醫療評估，也不適用於兒童、青少年或孕婦。

執行測試：`python -m unittest discover -s tests`

## 使用者與 BMI 歷史紀錄

計算時可選填姓名（最多 80 個字），成功計算後會儲存身高、體重、BMI 與計算時間。
相同姓名（去除前後空白後）會歸在同一位使用者；未填姓名仍可計算，但不儲存。
頁面上方的「使用者紀錄」會列出所有已儲存紀錄的使用者，點選姓名可查看歷次結果，最新紀錄排在最前，時間顯示為台灣時間（UTC+8）。

此版本依姓名區分使用者，沒有登入或存取限制，所有訪客都能查看姓名與紀錄；同名視為同一人。
啟用此功能之前算過的 BMI 沒有儲存，無法回溯。

紀錄使用 Python 內建 SQLite，無須另裝資料庫套件。本機預設儲存在 `instance/history.sqlite3`（已由 `.gitignore` 排除）。
在 Azure App Service 預設儲存於 `%HOME%/data/bmi/<WEBSITE_SLOT_NAME>/history.sqlite3`，位於部署目錄之外；未提供 slot 名稱時使用 `production`，讓正式與測試環境分開保存紀錄。
可用環境變數 `BMI_DATABASE_PATH` 指定其他資料庫檔案位置；多台執行個體或高併發部署應另接共用資料庫。

## 部署到 Azure Web App

`.github/workflows/deploy-azure.yml` 在 `main` 分支的應用程式、測試或 workflow 異動時執行，也可以從 GitHub Actions 手動觸發。流程會在 Windows runner 上執行測試、下載官方 Python 3.14.8 可嵌入版本，將 Python 與相依套件一起部署到 `NTUSTweb00`（資源群組 `NTUSTlab2026`）。站點透過 `web.config` 的 IIS HttpPlatformHandler 啟動 `serve.py`，以 Waitress 提供 Flask 服務。

此方法使用**隨部署包提供的 Python**，不依賴 Windows App Service 內建 Python 執行環境；HttpPlatformHandler 必須在目標站點可用。`NTUSTweb00` 目前是 Windows Web App，部署時會確認作業系統。

在 GitHub 儲存庫 **Settings → Secrets and variables → Actions** 確認：

- Repository secret `AZURE_CREDENTIALS`：Azure 服務主體的 `clientId`、`clientSecret`、`subscriptionId`、`tenantId` 組成的 JSON。此 Secret 已設定，不要把內容寫進程式碼。

請確認該服務主體對 `NTUSTweb00` 具有部署權限（例如該站點的 **Website Contributor**）。推送符合上述條件的 `main` 分支異動，或從 GitHub Actions 手動執行工作流程即可部署。
