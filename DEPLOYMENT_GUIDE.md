# 🚀 Complete Deployment Guide: Backend on Render + Frontend on Netlify

## Overview
- **Backend (Django)**: Deploying to Render with Docker
- **Frontend (React + Vite)**: Deploying to Netlify
- **Database**: MongoDB Atlas (Cloud-hosted)

---

## Part 1: Prerequisites Setup

### 1.1 Create GitHub Repository (Required)
Both Render and Netlify need your code in GitHub for automatic deployments.

1. Go to [github.com](https://github.com) and create a new repository
2. Name it (e.g., `NOVAHAMO_HR_Management`)
3. Initialize with no README (you have one already)
4. Clone your new repo locally:
   ```bash
   git clone <your-repo-url>
   cd <your-repo-name>
   ```
5. Copy all your project files into this folder
6. Push to GitHub:
   ```bash
   git add .
   git commit -m "Initial commit"
   git push -u origin main
   ```

### 1.2 Create MongoDB Atlas Account (Required)
Your app uses MongoDB, so you need a cloud database.

1. Go to [mongodb.com/cloud](https://www.mongodb.com/cloud)
2. Create a free account
3. Create a new project
4. Create a **free tier cluster** (M0)
5. Get your connection string:
   - Click "Connect" on your cluster
   - Choose "Drivers"
   - Copy the connection string (looks like: `mongodb+srv://username:password@cluster.mongodb.net/database`)
6. **Important**: Go to **Network Access** and **Allow access from anywhere** (0.0.0.0/0)
   - This is necessary because Render doesn't have a static IP

### 1.3 Create Accounts (if not already done)
- **Render**: [render.com](https://render.com) - Sign up with GitHub
- **Netlify**: [netlify.com](https://netlify.com) - Sign up with GitHub

---

## Part 2: Backend Deployment on Render

### Step 1: Create `runtime.txt` (Python Version)
In your `backend/` folder, create a `runtime.txt` file:

```
python-3.12.1
```

This tells Render which Python version to use.

### Step 2: Update Django Settings for Production

Edit `backend/hr_management/settings.py`:

```python
# Find ALLOWED_HOSTS and update it:
ALLOWED_HOSTS = ['*']  # In production, replace * with your domain

# Find DEBUG and update it:
DEBUG = os.getenv('DEBUG', 'False').lower() in ('1', 'true', 'yes')

# Add CORS settings (if not already present)
CORS_ALLOWED_ORIGINS = [
    "https://your-netlify-domain.netlify.app",  # Add your frontend URL later
    "http://localhost:3000",
]

# Add CSRF settings
CSRF_TRUSTED_ORIGINS = [
    "https://your-netlify-domain.netlify.app",
    "http://localhost:3000",
]
```

### Step 3: Update `requirements.txt` (Add Gunicorn & CORS)

Add these lines to `backend/requirements.txt`:

```
gunicorn>=21.0
django-cors-headers>=4.0
whitenoise>=6.0
```

Then run:
```bash
pip install -r requirements.txt
```

### Step 4: Create `.env.example` File

In `backend/` folder, create `.env.example`:

```
DEBUG=False
DJANGO_SECRET_KEY=your-secret-key-here
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/dbname
```

### Step 5: Update `settings.py` to Use Environment Variables

Add MongoDB configuration to `settings.py`:

```python
# Add this import at the top
import pymongo

# Add this after DATABASES section
MONGO_CLIENT = None

def get_mongo_db():
    global MONGO_CLIENT
    if MONGO_CLIENT is None:
        mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/hr_management')
        MONGO_CLIENT = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    return MONGO_CLIENT
```

### Step 6: Create Render Web Service

1. Go to [render.com/dashboard](https://render.com/dashboard)
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repository
4. Fill in the details:
   - **Name**: `novahamo-hr-backend`
   - **Environment**: `Docker` (since you have a Dockerfile)
   - **Build Command**: (leave empty - Docker will handle it)
   - **Start Command**: 
     ```
     gunicorn hr_management.wsgi:application --bind 0.0.0.0:$PORT
     ```

5. Click **"Advanced"** and add Environment Variables:
   - `DEBUG`: `False`
   - `DJANGO_SECRET_KEY`: (Generate a random key - use an online Django secret key generator)
   - `MONGODB_URI`: (Your MongoDB connection string from Atlas)

6. Click **"Create Web Service"**

### Step 7: Deploy!
- Render will automatically start building and deploying
- Wait for the build to complete (5-10 minutes)
- You'll get a URL like: `https://novahamo-hr-backend.onrender.com`
- Copy this URL - you'll need it for the frontend

---

## Part 3: Frontend Deployment on Netlify

### Step 1: Update Frontend API Configuration

Edit `frontend/src/api/index.js`:

```javascript
const LOCAL_URL = "/api";
const PROD_URL = import.meta.env.VITE_API_URL || "https://novahamo-hr-backend.onrender.com/api";

const isLocal = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

const api = axios.create({
    baseURL: isLocal ? LOCAL_URL : PROD_URL,
    timeout: 60000,
});
```

Replace `https://novahamo-hr-backend.onrender.com` with your actual Render backend URL.

### Step 2: Create `netlify.toml` (Already Exists - Verify It)

Your `netlify.toml` looks good:

```toml
[build]
  base = "frontend"
  command = "npm run build"
  publish = "dist"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

This tells Netlify:
- Build from the `frontend` folder
- Run `npm run build` to build
- Publish the `dist` folder
- Redirect all routes to `index.html` (for React Router)

### Step 3: Deploy on Netlify

**Option A: Using Netlify UI (Recommended for First Time)**

1. Go to [netlify.com](https://netlify.com) and log in
2. Click **"Add new site"** → **"Import an existing project"**
3. Choose **GitHub** and authorize
4. Select your repository
5. Configure build settings:
   - **Base directory**: `frontend`
   - **Build command**: `npm run build`
   - **Publish directory**: `dist`
6. Click **"Deploy site"**
7. Netlify will build and deploy automatically
8. Get your URL (looks like: `https://your-site-name.netlify.app`)

**Option B: Using Netlify CLI (For Advanced Users)**

```bash
# Install Netlify CLI
npm install -g netlify-cli

# In your project root
netlify deploy --prod --dir=frontend/dist
```

### Step 4: Update Backend CORS Settings

After getting your Netlify URL, go back to Render:

1. Go to your Render backend service dashboard
2. Go to **Environment** settings
3. Update `CSRF_TRUSTED_ORIGINS` with your Netlify URL:
   ```
   https://your-site-name.netlify.app,http://localhost:3000
   ```
4. Trigger a redeploy

---

## Part 4: Post-Deployment Checklist

### ✅ Backend (Render)
- [ ] Render build successful
- [ ] No database connection errors in logs
- [ ] MongoDB Atlas IP whitelist includes 0.0.0.0/0
- [ ] Environment variables set correctly
- [ ] Health check endpoint working

### ✅ Frontend (Netlify)
- [ ] Build successful
- [ ] Site URL is accessible
- [ ] API calls go to Render backend
- [ ] Environment variable for API URL is correct
- [ ] React Router redirects working

### ✅ Integration Testing
- [ ] Login works from frontend
- [ ] Data loads from backend
- [ ] Can create/edit/delete data
- [ ] No CORS errors in browser console
- [ ] No 404 errors for API calls

---

## Part 5: Troubleshooting

### Issue: "Cannot connect to MongoDB"
**Solution**: 
1. Verify connection string in Render environment variables
2. Check MongoDB Atlas Network Access includes 0.0.0.0/0
3. Verify database name in connection string matches MongoDB

### Issue: "CORS errors" in browser console
**Solution**:
1. Update `CSRF_TRUSTED_ORIGINS` in Django settings
2. Verify `SimpleCorsMiddleware` is properly configured in `settings.py`
3. Check that frontend URL matches exactly in CORS settings

### Issue: "Frontend can't reach backend"
**Solution**:
1. Check `VITE_API_URL` environment variable is set correctly in Netlify
2. Verify Render backend URL is accessible (check status page)
3. Check browser console for exact error message

### Issue: "Render build fails"
**Solution**:
1. Check build logs in Render dashboard
2. Verify `requirements.txt` has all dependencies
3. Check `runtime.txt` has valid Python version
4. Verify `Dockerfile` is correct

### Issue: "Static files not loading"
**Solution**:
1. Run `python manage.py collectstatic` locally
2. Verify `STATIC_ROOT` and `STATIC_URL` in settings.py
3. Consider using WhiteNoise for serving static files

---

## Part 6: Continuous Deployment Setup

### Auto-Deploy on Git Push
Both Render and Netlify automatically redeploy when you push to GitHub:

1. Make changes locally
2. Commit and push:
   ```bash
   git add .
   git commit -m "Your message"
   git push origin main
   ```
3. Both Render and Netlify will automatically rebuild and deploy

### View Logs
- **Render**: Dashboard → Your service → "Logs" tab
- **Netlify**: Dashboard → Your site → "Deploys" tab → "Deploy log"

---

## Part 7: Environment Variables Summary

### Backend (Render) - Set These in Render Dashboard
```
DEBUG=False
DJANGO_SECRET_KEY=<generate-random-key>
MONGODB_URI=<your-mongodb-connection-string>
CSRF_TRUSTED_ORIGINS=https://your-netlify-url.netlify.app,http://localhost:3000
```

### Frontend (Netlify) - Set These in Netlify Dashboard
```
VITE_API_URL=https://your-render-backend.onrender.com/api
```

---

## Quick Command Reference

```bash
# Local development
cd backend
python manage.py runserver  # Backend on localhost:8000

cd ../frontend
npm install
npm run dev  # Frontend on localhost:3000

# Generate Django secret key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Test production build locally
cd frontend
npm run build
npm run preview
```

---

## Additional Resources

- **Render Documentation**: https://render.com/docs
- **Netlify Documentation**: https://docs.netlify.com
- **MongoDB Atlas**: https://www.mongodb.com/docs/atlas/
- **Django Deployment**: https://docs.djangoproject.com/en/stable/howto/deployment/
- **Vite Deployment**: https://vitejs.dev/guide/static-deploy.html

---

## Need Help?

If you encounter issues:
1. Check the logs (Render dashboard or Netlify dashboard)
2. Review this guide's troubleshooting section
3. Compare your settings with the checklist above
4. Check that all environment variables are set correctly

Good luck with your deployment! 🚀
