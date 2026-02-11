# K_AutoApply

Automated Job Application Service for Kangrats - Sends job applications via browser automation.

## 🚀 Quick Start

### With Docker (Recommended)

```bash
docker-compose up -d
```

API available at `http://localhost:8001`

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run
uvicorn app.main:app --reload --port 8001
```

## 📡 API Endpoints

### Applications

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/applications` | Create single application |
| POST | `/api/applications/batch` | Create multiple applications |
| GET | `/api/applications` | List applications (paginated) |
| GET | `/api/applications/{id}` | Get single application |
| GET | `/api/applications/stats` | Get statistics |
| GET | `/api/applications/runs` | Get processing runs history |
| POST | `/api/applications/process` | Process pending applications |
| GET | `/api/applications/process/status` | Check if processing |
| POST | `/api/applications/{id}/retry` | Retry failed application |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| GET | `/health` | Health check |

## 📝 Usage

### 1. Create Application

```bash
curl -X POST http://localhost:8001/api/applications \
  -H "Content-Type: application/json" \
  -d '{
    "job_url": "https://www.helplavoro.it/offerta/12345.html",
    "job_title": "Software Developer",
    "company_name": "Acme Corp",
    "candidate": {
      "name": "Mario Rossi",
      "email": "mario.rossi@example.com",
      "phone": "+39 333 1234567",
      "message": "Sono interessato alla posizione...",
      "cv_reference": "mario_rossi_cv.pdf"
    }
  }'
```

### 2. Create Batch Applications

```bash
curl -X POST http://localhost:8001/api/applications/batch \
  -H "Content-Type: application/json" \
  -d '{
    "applications": [
      {
        "job_url": "https://www.helplavoro.it/offerta/12345.html",
        "candidate": {
          "name": "Mario Rossi",
          "email": "mario@example.com",
          "cv_reference": "mario_cv.pdf"
        }
      },
      {
        "job_url": "https://www.helplavoro.it/offerta/67890.html",
        "candidate": {
          "name": "Luigi Verdi",
          "email": "luigi@example.com",
          "cv_reference": "luigi_cv.pdf"
        }
      }
    ]
  }'
```

### 3. Process Applications

```bash
curl -X POST "http://localhost:8001/api/applications/process?limit=10"
```

### 4. Check Status

```bash
curl http://localhost:8001/api/applications/stats
```

## 📁 CV Loader

The service supports multiple CV sources via Factory pattern:

### Local Files (default)
```env
CV_LOADER_TYPE=local
CV_BASE_PATH=./cvs
```
Place CV files in `./cvs/` folder, reference by filename.

### URL
```env
CV_LOADER_TYPE=url
```
Pass full URL as `cv_reference`.

### Azure Blob Storage
```env
CV_LOADER_TYPE=azure_blob
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
AZURE_CONTAINER_NAME=cvs
```

### AWS S3
```env
CV_LOADER_TYPE=s3
```
Pass `bucket-name/path/to/cv.pdf` as `cv_reference`.

## 🗄️ Database Schema

### Applications Table
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| job_url | string | Job listing URL |
| job_title | string | Job title |
| company_name | string | Company name |
| candidate_name | string | Candidate full name |
| candidate_email | string | Candidate email |
| candidate_phone | string | Candidate phone |
| candidate_message | string | Cover letter/message |
| cv_reference | string | CV path/URL |
| status | enum | pending/processing/success/failed/skipped |
| error_message | string | Error details if failed |
| screenshot_path | string | Screenshot path |
| created_at | datetime | Created timestamp |
| started_at | datetime | Processing started |
| completed_at | datetime | Processing completed |
| attempts | int | Number of attempts |
| max_attempts | int | Max retry attempts (default: 3) |

### Application Runs Table
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| started_at | datetime | Run started |
| finished_at | datetime | Run finished |
| total_processed | int | Total processed |
| successful | int | Successful applications |
| failed | int | Failed applications |
| skipped | int | Skipped applications |
| status | string | running/completed/failed |

## 🔧 Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/autoapply.db` | Database connection |
| `CV_LOADER_TYPE` | `local` | CV source type |
| `CV_BASE_PATH` | `./cvs` | Local CV folder |
| `HEADLESS` | `true` | Run browser headless |
| `SLOW_MO` | `100` | Delay between actions (ms) |
| `DELAY_BETWEEN_APPLICATIONS` | `5.0` | Delay between applications (s) |
| `MAX_APPLICATIONS_PER_RUN` | `50` | Max applications per run |
| `SAVE_SCREENSHOTS` | `true` | Save screenshots |

## 🐳 Docker

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Rebuild
docker-compose up -d --build
```

## 📊 Integration with Kangrats

```
┌─────────────┐      ┌─────────────────┐      ┌─────────────┐
│ K_Scraper   │      │ Kangrats        │      │ K_AutoApply │
│             │      │ (Matching)      │      │             │
├─────────────┤      ├─────────────────┤      ├─────────────┤
│ Scrape jobs │─────▶│ Match candidate │─────▶│ POST /api/  │
│ GET /api/   │ API  │ to jobs         │ API  │ applications│
│ jobs        │      │                 │      │             │
└─────────────┘      └─────────────────┘      └─────────────┘
```

## 📝 License

Proprietary - Kangrats / Limyra S.r.l.
