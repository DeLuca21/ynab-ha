# YNAB Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
![GitHub Release](https://img.shields.io/github/v/release/DeLuca21/hacs-ynab?include_prereleases)
![GitHub Downloads](https://img.shields.io/github/downloads/DeLuca21/hacs-ynab/latest/total)


<p align="center">
  <img src="https://raw.githubusercontent.com/DeLuca21/hacs-ynab/refs/heads/main/raw/main/assets/yanb_logo.png?token=GHSAT0AAAAAAC7MA24YUCZRZCIEPZNPZF3GZ6CQSAA" alt="YNAB Logo" width="300">
</p>
<p align="center">
  <a href="https://ko-fi.com/DeLuca21" target="_blank">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" height="35" alt="Support me on Ko-fi" />
  </a>
  <a href="https://buymeacoffee.com/DeLuca21" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174">
  </a>
</p>

**YNAB Custom** is a Home Assistant integration that allows you to seamlessly track and manage your **You Need A Budget (YNAB)** data—accounts, budgets, categories, and more—directly in Home Assistant.

---

## 🚀 Features

- **Multiple Budgets**: Configure more than one YNAB budget at once.
- **Custom Budget “Instance Name”**: Each budget can have a unique prefix (e.g., “Mel,” “Jamie”) to avoid entity ID collisions.
- **Configurable Update Intervals**: Choose how frequently each budget’s data is refreshed.
- **Account Balances**: Pull real-time balances for any on-budget account.
- **Category Sensors**: Track each category’s **Assigned**, **Activity**, and **Balance**.
- **Category Group Summaries**: Summaries for groups of categories (e.g., “Household,” “Groceries”) showing total assigned/activity/balance.
- **Budget-Wide Summary Sensors**: Get an aggregated total for assigned, activity, or balance across **all** categories in the budget.
- **Manual Refresh Service**: Trigger an immediate data update from YNAB.
- **Friendly Entities**: Customizable entity names to prevent name collisions.

---

## 📥 Installation via HACS

### HACS (Home Assistant Community Store)

1. **Ensure HACS is installed.** If you haven’t yet installed HACS, follow the [HACS installation guide](https://hacs.xyz/docs/installation/manual).
2. Open **HACS** in Home Assistant.
3. Click the **three-dot menu** (⋮) and select **"Custom repositories"**.
4. Add the repository:
   ```
   https://github.com/DeLuca21/hacs-ynab
   ```
   and pick **"Integration"** from the category dropdown.
5. Click **"ADD"**.
6. Search for **"YNAB Custom"** in HACS and install the integration.
7. **Restart Home Assistant** to finalize the installation.

### Manual Installation

1. Download the latest release from the [YNAB GitHub repository](https://github.com/DeLuca21/hacs-ynab/releases).
2. Unzip the downloaded file and place the `ynab_custom` folder inside your `custom_components` directory (e.g., `/config/custom_components/ynab_custom`).
3. **Restart Home Assistant**.

---

## 🔧 Configuration

1. Go to **Settings → Devices & Services → Integrations** in Home Assistant.
2. Click **"+ Add Integration"** and search for **"YNAB Custom"**.
3. **Enter your YNAB API Key** (instructions below).
4. **Select your budget** from the dropdown.
5. **Set an Instance Name** (optional) if you plan to manage multiple budgets.
6. Pick your **preferred currency** (USD, EUR, etc.).
7. On the next screen, you can adjust optional settings like **update interval** (refresh frequency) and enabling **category group** or **budget-wide** summary sensors.

### Obtaining Your YNAB API Key

1. Go to [**YNAB Developer Settings**](https://app.ynab.com/settings/developer).
2. Click **"New Token"** to generate a personal access token.
3. Copy the API Key and use it when setting up the integration.

---

## 📊 Sensors Created

Below are examples showing how sensors might be named if you set a particular **instance_name** (e.g., `<instance_name>`). Adjust the placeholders accordingly.

- **Account Balances**  
  `sensor.ynab_<instance_name>_<accountid>_balance`  
  Each tracks a single account’s balance.

- **Category Sensors** (Assigned, Activity, Balance)  
  `sensor.ynab_<instance_name>_<categoryid>_budgeted`  
  `sensor.ynab_<instance_name>_<categoryid>_activity`  
  `sensor.ynab_<instance_name>_<categoryid>_balance`

- **Category Group Summaries** (assigned, activity, balance)  
  `sensor.ynab_<groupid>_assigned_<instance_name>`  
  `sensor.ynab_<groupid>_activity_<instance_name>`  
  `sensor.ynab_<groupid>_balance_<instance_name>`

- **Budget-Wide Summary** (assigned, activity, balance)  
  `sensor.ynab_entire_budget_activity_<instance_name>`  
  `sensor.ynab_entire_budget_assigned_<instance_name>`  
  `sensor.ynab_entire_budget_balance_<instance_name>`

- **YNAB API Status**  
  `sensor.ynab_api_<instance_name>_status`  
  Indicates whether the last update was successful.

---

## 🔄 Manual Refresh

Use the following service to trigger an immediate data refresh from YNAB:
```yaml
service: ynab_custom.refresh
```

---

## 🛠 Issues & Support

- If you encounter problems, open an [issue on GitHub](https://github.com/DeLuca21/hacs-ynab/issues).
- Pull requests and feature suggestions are welcome.

If you like this integration and want to support my work:

☕ [**Buy Me a Coffee**](https://www.buymeacoffee.com/DeLuca21)
💙 [**Support me on Ko-fi**](https://ko-fi.com/DeLuca21)
  
🚀 **Happy budgeting with Home Assistant!**
