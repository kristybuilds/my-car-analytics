# ⚡ Malaysia Car Analytics Pipeline

**Problem Statement: Bridging the "EV Insight Gap" in Malaysia**

As a Malaysian observer, I found it difficult to move beyond anecdotal evidence (e.g., "charging is only easy in the Klang Valley") to find data-driven answers to these critical questions:

1. Is EV adoption outpacing infrastructure? Does a high number of EVs in a state necessarily mean it has the chargers to support them?

2. Are certain states being left behind? How does the "EV Readiness Ratio" differ when comparing industrialized hubs to developing regions?

3. How fast is the shift actually happening? Is the growth of EVs and Hybrids a recent "spike," or a steady trend across the last decade?

## 💡 The Solution: A Statewide EV Readiness & Trend Pipeline

This project solves this information gap by engineering a centralized, end-to-end data pipeline that transforms fragmented government data into a comparative State-Level Readiness Index and Historical Trend Analysis.

1. Regional Normalization: Engineered a transformation layer that maps raw JPJ registration data to ISO-3166-2 geo-codes, allowing for a side-by-side comparison of all 13 states and 3 federal territories.

2. The Readiness Metric: Created a custom EV-per-Plug Ratio. This metric normalizes the data, showing exactly how many vehicles are "competing" for each public charging point in a specific region, identifying infrastructure bottlenecks.

3. Longitudinal Fuel Analysis: Analyzed over 20 years of registration data to visualize the transition from traditional Internal Combustion Engines (ICE) to Hybrid and Battery Electric Vehicles (BEV), providing a clear picture of market sentiment and adoption velocity.

4. Infrastructure Transparency: Built an interactive dashboard that allows any stakeholder to visualize these trends and infrastructure gaps without relying on high-level national summaries.

## 📊 Business Value & Insights
The core of this project is the **EV Readiness Ratio**, a ratio-based metric that identifies infrastructure bottlenecks across 13 states and 3 federal territories.

* **View Live Dashboard:** [Looker Studio Analysis](https://datastudio.google.com/s/ppDcKOajeJE)
* **Key Discovery:** Identified that while **Kuala Lumpur (MY-14)** has the most EVs, **Perlis (MY-09)** and **Sabah (MY-12)** face the highest "Readiness Strain," with ratios exceeding 20 vehicles per plug.

---

## Architecture

---

## Dataset

| Dataset | Source | Description |
| :--- | :--- | :--- |
| **Vehicle Registrations** | https://data.gov.my/data-catalogue/registration_transactions_all | Historical registration data (2000–Present) categorized by fuel type and manufacturer. |
| **Charging Infrastructure** | https://www.planmalaysia.gov.my/mevnet/ | Publicly available charging stations, including plug types (AC/DC) and active status. |

---

## 🛠 Tech Stack
This project uses a hybrid cloud approach. Airflow is hosted locally via Docker to minimize GCP costs, while all heavy data processing (BigQuery/Dataform) is offloaded to the Google Cloud infrastructure via the gcloud Application Default Credentials (ADC).

* **IaC:** Terraform (GCP Provider)
* **Orchestration:** Apache Airflow (Dockerized)
* **Data Warehouse:** Google BigQuery
* **Transformation:** Dataform (SQLX)
* **Visualization:** Looker Studio

---

## 🚀 Setup & Deployment

### 1. Infrastructure (Terraform)
We use Infrastructure as Code to provision the environment.
1.  Initialize the project: `terraform init`
2.  Create your `terraform.tfvars` (refer to `terraform.tfvars.example`).
3.  Deploy GCP resources: `terraform apply`
    * *This creates BigQuery datasets (Bronze, Silver, Gold), Secret Manager entries, and required Service Accounts.*

### 2. Secure GitHub-GCP Integration
To enable Dataform to pull transformation code securely:
1.  Generate a **GitHub Personal Access Token (PAT)**.
2.  The `terraform apply` step provisions a **GCP Secret Manager** slot for this token.
3.  Link your Dataform repository in the GCP Console using this secret to establish a secure handshake.

### 3. Pipeline Orchestration (Airflow)
The pipeline runs locally via Docker but executes workloads in the cloud.
1.  **Authenticate:** `gcloud auth application-default login`
2.  **Spin up containers:** `docker-compose up -d`
3.  **Trigger DAG:** Access the Airflow UI at `localhost:8080`. The DAG handles:
    * **Ingestion:** Moves raw JPJ and Gentari/Charger data to BigQuery.
    * **Normalization:** Cleans state names and maps **ISO-3166-2** codes (e.g., `MY-12` for Sabah).
    * **Aggregation:** Calculates the final Readiness Index in the Gold layer.

---

## 📐 Data Architecture
| Layer | Logic | Purpose |
| :--- | :--- | :--- |
| **Bronze** | Raw Ingestion | Immutable copy of vehicle and charger data. |
| **Silver** | Transformation | Data cleaning, state normalization, and geo-coding. |
| **Gold** | Analysis | Final metrics: `ev_per_plug_ratio` and Market Share. |

---

## 🛡 Security & Repository Cleanliness
To maintain a professional repo, the following are strictly ignored via `.gitignore`:
* **Terraform State:** `.tfstate` files are kept local to prevent state-locking issues.
* **Secrets:** All API keys and Project IDs are managed via `.tfvars`.
* **Binaries:** Large `.zip` or executable files are excluded to keep the repository lightweight.

---

**Last Updated:** April 2026