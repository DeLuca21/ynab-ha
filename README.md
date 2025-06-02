# YNAB Integration for Home Assistant

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge&labelColor=%23585b70&color=%23b4befe&logo=home-assistant)](https://hacs.xyz/)
[![GitHub License](https://img.shields.io/github/license/DeLuca21/ynab-ha?style=for-the-badge&labelColor=%23585b70&color=%23f5e0dc&logo=github)](https://github.com/DeLuca21/ynab-ha)
[![GitHub Release](https://img.shields.io/github/v/release/DeLuca21/ynab-ha?include_prereleases&style=for-the-badge&labelColor=%23585b70&color=%23cba6f7&logo=github)](https://github.com/DeLuca21/ynab-ha/releases)
[![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/DeLuca21/ynab-ha/total?style=for-the-badge&label=Downloads&labelColor=%23585b70&color=%23a6da95&logo=github)](https://github.com/DeLuca21/ynab-ha/releases)
[![GitHub Clones](https://img.shields.io/badge/dynamic/json?label=Clones&query=count&url=https://gist.githubusercontent.com/DeLuca21/3b1c308a20fd07024b4bdfc7916ca3e2/raw/clone.json&logo=github&style=for-the-badge&labelColor=%23585b70&color=%23a6da95)](https://github.com/MShawon/github-clone-count-badge)
[![GitHub Issues or Pull Requests](https://img.shields.io/github/issues/DeLuca21/ynab-ha?style=for-the-badge&labelColor=%23585b70&color=%23eba0ac&logo=github)](https://github.com/DeLuca21/ynab-ha/issues)


---


<p align="center">
  <img src="https://raw.githubusercontent.com/DeLuca21/ynab-ha/refs/heads/main/assets/yanb_logo.png" alt="YNAB Logo" width="300">
</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/DeLuca21/ynab-ha/refs/heads/main/assets/works_with_ynab.svg" alt="Works With YNAB Logo" width="300">
</p>
<p align="center">
  <a href="https://ko-fi.com/DeLuca21" target="_blank">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" height="35" alt="Support me on Ko-fi" />
  </a>
  <a href="https://buymeacoffee.com/DeLuca21" target="_blank">
    <img src="https://cdn.buymeacoffee.com/buttons/default-red.png" alt="Buy Me A Coffee" height="41" width="174">
  </a>
</p>

---

##  What's New in v1.3.1?



This version introduces smarter handling of **hidden categories**, improving dashboard clarity:

- Hidden YNAB categories now include a `hidden: true` attribute.
- Sensor names auto-append `(Hidden)` if the category is hidden in YNAB.
- This makes it easy to exclude legacy or unused categories using templates.

---

## 🚀 Features

- **Multiple Budgets**: Configure multiple YNAB budgets.
- **Configurable Update Intervals**: Choose how frequently each budget’s data is refreshed.
- **Account Balances**: Pull real-time balances for any on-budget account and associated attributes.
- **Category Sensors**: Track each category’s balances and associated attributes.
- **Custom Budget “Instance Name”**: Each budget can have a unique prefix (e.g., “Mel,” “Jamie”) to avoid entity ID collisions. (Defaults to the YNAB budget name)
- **Currency Selection**: Choose your preferred currency (USD, EUR, etc.).
- **Monthly Summary Sensors**: Retrieve current month's summary data with associated attributes (e.g., `Budgeted`, `Activity`, `To Be Budgeted`, `Age of Money`).

---

## 📸 Screenshots

Below are screenshots showcasing an example card on a dashboard, the integration setup and how YNAB data appears in Home Assistant.  

You can see the **dashboard card example, setup flow, account details, category insights, and the new monthly summary sensor** in action.  

<p align="center">
  <table>
    <tr>
      <td align="center"><img src="https://raw.githubusercontent.com/DeLuca21/ynab-ha/refs/heads/main/assets/screenshots/dashboard_example.png" alt="Monthly Summary" width="200"></td>
      <td align="center"><img src="https://raw.githubusercontent.com/DeLuca21/ynab-ha/refs/heads/main/assets/screenshots/setup_flow.png" alt="Setup Flow" width="200"></td>
      <td align="center"><img src="https://raw.githubusercontent.com/DeLuca21/ynab-ha/refs/heads/main/assets/screenshots/account_example.png" alt="Accounts" width="200"></td>
      <td align="center"><img src="https://raw.githubusercontent.com/DeLuca21/ynab-ha/refs/heads/main/assets/screenshots/category_example.png" alt="Categories" width="200"></td>
      <td align="center"><img src="https://raw.githubusercontent.com/DeLuca21/ynab-ha/refs/heads/main/assets/screenshots/monthly_summary.png" alt="Monthly Summary" width="200"></td>
    </tr>
  </table>
</p>


---

## 📥 Installation via HACS

### HACS (Home Assistant Community Store)

1. **Ensure HACS is installed.** If you haven’t yet installed HACS, follow the [HACS installation guide](https://hacs.xyz/docs/installation/manual).
2. Open **HACS** in Home Assistant.
3. Click the **three-dot menu** (⋮) and select **"Custom repositories"**.
4. Add the repository:
```
https://github.com/DeLuca21/ynab-ha
```
5. and pick **"Integration"** from the category dropdown.
6. Click **"ADD"**.
7. Search for **"YNAB Custom"** in HACS and install the integration.
8. **Restart Home Assistant** to finalize the installation.

### Manual Installation

1. Download the latest release from the [GitHub repository](https://github.com/DeLuca21/ynab-ha/releases).
2. Unzip the downloaded file and place the `ynab_custom` folder inside your `custom_components` directory (e.g., `/config/custom_components/ynab_custom`).
3. **Restart Home Assistant**.

---

## 🔧 Configuration

1. Go to **Settings → Devices & Services → Integrations** in Home Assistant.
2. Click **"+ Add Integration"** and search for **"YNAB Integration for Home Assistant"**.
3. Enter your **YNAB API Key** (see below for instructions).
4. Accept **terms and conditions**
5. **Select your budget** from the dropdown/list.
6. Choose an **instance_name** or leave default.
7. Pick your **preferred currency** (USD, EUR, etc.).
8. Choose your desired **update_interval** or leave default (Longer intervals are better to not make too many API calls and not be rate limited).
9. Select **Accounts & Categories** to include or leave as **Select All**.

### Obtaining Your YNAB API Key

1. Go to [**YNAB Developer Settings**](https://app.ynab.com/settings/developer).
2. Click **"New Token"** to generate a personal access token.
3. Copy the API Key and use it during integration setup.

---

## 📊 Sensors Created

YNAB data is now represented with **fewer sensors** but **richer attributes**.

### **Accounts**

Each YNAB account now has **one sensor** with relevant attributes instead of multiple sensors.

#### **Attributes for Accounts:**

- **Balance** – The total balance of the account, including both cleared and uncleared transactions.
- **Cleared Balance** (Default state value) – The balance of transactions that have been processed and cleared.
- **Uncleared Balance** – The balance of pending transactions that have not yet cleared.
- **On Budget** – Indicates whether the account is included in the budget (`true` for budgeted accounts, `false` for tracking accounts).
- **Type** – The type of account (e.g., `Checking`, `Credit Card`, `Savings`).

### **Categories**

Each YNAB budget category now has **one sensor** with relevant attributes instead of multiple sensors.

#### **Attributes for Categories:**

- **Budgeted** – The amount of money assigned to this category for the current month.
- **Activity** – The total amount spent in this category during the current month (negative means an expense).
- **Balance** (Default state value) – The remaining funds available in this category after subtracting activity from budgeted.
- **Category Group** – The parent group this category belongs to (e.g., "Bills," "Groceries").
- **Goal Type** – The type of goal set for this category (e.g., `Target Balance`, `Monthly Funding`).
- **Goal Target** – The total amount you aim to allocate or save for this category.
- **Goal Percentage Complete** – The percentage of progress toward the goal, based on the balance and target.
- **Goal Overall Left** – Remaining amount needed to meet the goal target.
- **Percentage Spent** – How much of the current month’s budget has been spent (0 – 100 %+).
- **Needs Attention** – `true` if the category is overspent or under‑funded.
- **Attention Reason** – `"Overspent"`, `"Underfunded"`, or `"Ok"`.

### **Latest Monthly Summary**

You can now see the current months summary in  **one sensor** with relevant attributes.

#### **Attributes for Latest Monthly Summary:**

- **Budgeted** – The total amount of money assigned for the current month.
- **Activity** – (Default state value) The total amount spent for the current month.
- **To Be Budgeted** – The remaining funds available to be assigned for the current month.
- **Age Of Money** – The average age of your money, indicating financial stability.

---

## 🛠 Issues & Support

- Found a bug? Report it via [GitHub Issues](https://github.com/DeLuca21/ynab-ha/issues).
- Have a feature request? Feel free to suggest improvements.
- Pull requests are welcome!

---

## 🔄 Recent Updates


## 🎉 Version 1.3.0 Update


Four new **Category**‑sensor attributes for cleaner dashboards—no extra templates needed!

| Attribute           | What it does                                                             |
| ------------------- | ------------------------------------------------------------------------ |
| `percentage_spent`  | % of this month’s budget already spent (0 % when nothing budgeted).      |
| `needs_attention`   | **true / false** flag if the category is Overspent *or* Under‑funded.    |
| `attention_reason`  | `"Overspent"`, `"Underfunded"`, or `"Ok"` so you know why.               |
| `goal_overall_left` | Money still required to hit the goal target, converted to your currency. |

These are calculated inside the integration—no extra API calls, no new entities.  


---

## 🚀 Future Updates

I'm actively improving the YNAB integration and plan to introduce the following features in future updates:

- **Scheduled Transactions**: Support for upcoming transactions that haven't been processed yet.

- **Category Group Summaries & Budget-Wide Summaries**: Previously available but currently not included; I plan to explore reintroducing them in a similar method to the **Accounts, Categories & Monthly Summary**

- **Manual Refresh Service** (`ynab_custom.refresh`): Not present in this release but may return in a future update.

- **Integration "Configure" option** - This may be reintroduced in a future update.

- **Optional Exclusion of Hidden Categories** – Considering a toggle in the config flow to exclude hidden categories from being created as sensors, for cleaner dashboards.

---

## ☕ Support the Project

If you enjoy this integration, consider **supporting development**:

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/DeLuca21)  
[![BuyMeACoffee](https://cdn.buymeacoffee.com/buttons/default-red.png)](https://www.buymeacoffee.com/DeLuca21)

🚀 **Happy budgeting with Home Assistant!** 🎯

---

## Disclaimer

This YNAB for Home Assistant integration is not officially supported by You Need A Budget (YNAB) in any way. Use of this integration is at your own risk. Any issues or errors caused by this integration are not supported through YNAB's official support channels, and YNAB will not be able to troubleshoot or fix any problems related to it. Please use at your own risk!
