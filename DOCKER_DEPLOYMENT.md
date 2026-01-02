# 🐳 Docker Desktop Deployment Guide

## Quick Start (3 Steps)

### Step 1: Build the Docker Image
```powershell
cd "f:\Claude files\bulk-email-platform\python-email-sender"
docker-compose build
```

### Step 2: Start the Application
```powershell
docker-compose up -d
```

### Step 3: Access the UI
Open your browser to: **http://localhost:8000**

---

## 🚀 Docker Commands Reference

### **Start the Application**
```powershell
docker-compose up -d
```
- `-d` runs in detached mode (background)

### **Stop the Application**
```powershell
docker-compose down
```

### **View Logs**
```powershell
docker-compose logs -f
```
- `-f` follows logs in real-time

### **Restart the Application**
```powershell
docker-compose restart
```

### **Rebuild and Restart**
```powershell
docker-compose up -d --build
```

### **Check Status**
```powershell
docker-compose ps
```

---

## 📊 Docker Desktop Integration

### **View in Docker Desktop**
1. Open Docker Desktop
2. Go to "Containers" tab
3. You'll see: **bulk-email-sender**
4. Click on it to:
   - View logs
   - Open in browser (port 8000)
   - Stop/Start/Restart
   - View resource usage

### **Container Details**
- **Name**: `bulk-email-sender`
- **Port**: `8000:8000` (host:container)
- **Network**: `email-network`
- **Volume**: `postgres-data` (database persistence)

---

## 🔍 Health Checks

The container includes automatic health monitoring:
- **Check Interval**: Every 30 seconds
- **Endpoint**: `/api/test`
- **Timeout**: 10 seconds
- **Retries**: 3 attempts

**View Health Status**:
```powershell
docker inspect --format='{{.State.Health.Status}}' bulk-email-sender
```

---

## 💾 Data Persistence

### **Database Storage**
PostgreSQL stores data in a Docker volume for persistence:

```yaml
volumes:
  - postgres-data:/var/lib/postgresql/data
```

**Benefits**:
- ✅ Data survives container restarts
- ✅ Data survives container recreation
- ✅ Can backup and restore easily

### **Backup Database**
```powershell
docker exec bulk-email-postgres pg_dump -U bulk_email bulk_email > backup_$(Get-Date -Format 'yyyyMMdd').sql
```

### **Restore Database**
```powershell
Get-Content ./backup_20250119.sql | docker exec -i bulk-email-postgres psql -U bulk_email -d bulk_email
docker-compose restart
```

---

## 🛠️ Troubleshooting

### **Problem: Port Already in Use**
```powershell
# Find what's using port 8000
netstat -ano | findstr :8000

# Kill the local Python server first
# Or change port in docker-compose.yml:
ports:
  - "8080:8000"  # Use 8080 on host instead
```

### **Problem: Container Won't Start**
```powershell
# View detailed logs
docker-compose logs

# Check container status
docker ps -a

# Remove and recreate
docker-compose down
docker-compose up -d --build
```

### **Problem: Can't Access UI**
1. Check container is running: `docker ps`
2. Check logs: `docker-compose logs`
3. Visit health check: `http://localhost:8000/api/test`
4. Ensure no firewall blocking port 8000

### **Problem: Database Changes Not Persisting**
```powershell
# Check volume exists
docker volume ls | findstr postgres-data

# Inspect volume
docker volume inspect postgres-data
```

---

## 🔄 Complete Deployment Workflow

### **First Time Setup**
```powershell
# Navigate to project
cd "f:\Claude files\bulk-email-platform\python-email-sender"

# Build image
docker-compose build

# Start container
docker-compose up -d

# Check it's running
docker-compose ps

# View logs
docker-compose logs -f

# Access UI
start http://localhost:8000
```

### **Daily Use**
```powershell
# Start
docker-compose up -d

# Stop
docker-compose down

# View logs anytime
docker-compose logs -f
```

### **Updating Code**
```powershell
# Stop container
docker-compose down

# Make code changes
# ...

# Rebuild and restart
docker-compose up -d --build
```

---

## 📦 Docker Image Details

### **Base Image**
- `python:3.11-slim` (Debian-based, optimized)

### **Installed Dependencies**
- FastAPI
- Uvicorn
- SQLAlchemy
- Jinja2
- All dependencies from requirements.txt

### **Working Directory**
- `/app` inside container

### **Port**
- `8000` (mapped to host port 8000)

### **Entry Point**
- `python main.py`

---

## 🌐 Accessing the Application

### **From Your Computer**
```
http://localhost:8000
```

### **From Docker Desktop**
1. Click on `bulk-email-sender` container
2. Click "Open in Browser" button
3. Or click the port link (8000:8000)

### **From Other Computers (same network)**
```
http://YOUR-IP-ADDRESS:8000
```

Find your IP:
```powershell
ipconfig
# Look for IPv4 Address
```

---

## 🔐 Production Considerations

### **For Production Deployment**:

1. **Use Environment Variables**
   ```yaml
   environment:
     - DATABASE_URL=postgresql+psycopg2://bulk_email:bulk_email@db:5432/bulk_email
     - SECRET_KEY=your-secret-key-here
     - ALLOWED_HOSTS=yourdomain.com
   ```

2. **Add SSL/HTTPS**
   - Use nginx reverse proxy
   - Add Let's Encrypt certificates

3. **Resource Limits**
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '1'
         memory: 512M
   ```

4. **Use Secrets for Sensitive Data**
   - Don't put API keys in docker-compose.yml
   - Use Docker secrets or env files

---

## 📊 Monitoring

### **View Container Stats**
```powershell
docker stats bulk-email-sender
```

Shows:
- CPU usage
- Memory usage
- Network I/O
- Disk I/O

### **View Container Logs**
```powershell
# Last 50 lines
docker-compose logs --tail=50

# Follow in real-time
docker-compose logs -f

# Since specific time
docker-compose logs --since 10m
```

---

## 🧹 Cleanup

### **Remove Container (Keep Data)**
```powershell
docker-compose down
```

### **Remove Container and Volume (Delete Data)**
```powershell
docker-compose down -v
```

### **Remove Images**
```powershell
docker-compose down --rmi all
```

### **Complete Cleanup**
```powershell
docker-compose down -v --rmi all
docker system prune -a
```

---

## ✅ Verification Checklist

After deployment, verify:

- [ ] Container is running: `docker ps`
- [ ] Health check is passing: `docker inspect --format='{{.State.Health.Status}}' bulk-email-sender`
- [ ] UI is accessible: Visit http://localhost:8000
- [ ] API is working: Visit http://localhost:8000/api/test
- [ ] Database persists: Create campaign, restart container, check if still there
- [ ] Logs are clean: `docker-compose logs` shows no errors

---

## 🎯 Common Use Cases

### **Development**
```powershell
# Start with logs visible
docker-compose up

# Or start in background
docker-compose up -d
docker-compose logs -f
```

### **Testing**
```powershell
# Fresh start
docker-compose down -v
docker-compose up -d --build
```

### **Production**
```powershell
# Start with restart policy
docker-compose up -d

# Monitor
docker-compose logs -f
```

---

## 🚀 Next Steps

1. **Start the container**: `docker-compose up -d`
2. **View in Docker Desktop**: Open Docker Desktop → Containers
3. **Access UI**: http://localhost:8000
4. **Check logs**: `docker-compose logs -f`
5. **Configure providers**: Use the modern UI
6. **Create campaigns**: Start sending emails!

---

## 📞 Support

### **Check Application Status**
```powershell
curl http://localhost:8000/api/test
```

Should return:
```json
{
  "status": "success",
  "message": "API is working correctly!",
  "database": "connected",
  "version": "1.0.0"
}
```

### **Container Won't Start?**
1. Check Docker Desktop is running
2. Check no other app using port 8000
3. View logs: `docker-compose logs`
4. Try rebuilding: `docker-compose up -d --build`

---

## 🎉 You're Ready!

Your modern email platform is now containerized and ready to run on Docker Desktop!

**Quick Start**:
```powershell
docker-compose up -d
start http://localhost:8000
```

That's it! 🚀
