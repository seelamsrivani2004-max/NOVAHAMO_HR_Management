# 📋 Deployment Quick Checklist

## ⚡ Quick Steps Summary (Follow in Order)

### STEP 1️⃣: Prepare GitHub Repository (5 mins)
- [ ] Create repository on github.com
- [ ] Clone locally or push existing code
- [ ] Ensure all files are committed and pushed to `main` branch

### STEP 2️⃣: Setup MongoDB Atlas (10 mins)
- [ ] Create account at mongodb.com/cloud
- [ ] Create free M0 cluster
- [ ] Get connection string
- [ ] Go to Network Access → Allow from anywhere (0.0.0.0/0)
- [ ] Copy connection string (format: `mongodb+srv://user:pass@cluster.mongodb.net/dbname`)

### STEP 3️⃣: Deploy Backend to Render (15 mins)
- [ ] Sign up at render.com with GitHub
- [ ] Click "New +" → "Web Service"
- [ ] Select your GitHub repository
- [ ] Set **Name**: `novahamo-hr-backend`
- [ ] Set **Environment**: Docker
- [ ] Set **Start Command**: 
  ```
  gunicorn hr_management.wsgi:application --bind 0.0.0.0:$PORT
  ```
- [ ] Click **Advanced** and add Environment Variables:
  ```
  DEBUG=False
  DJANGO_SECRET_KEY=<generate-random-key>
  MONGODB_URI=<your-connection-string>
  CSRF_TRUSTED_ORIGINS=https://your-netlify-url.netlify.app,http://localhost:3000
  ```
- [ ] Click "Create Web Service"
- [ ] **⏳ Wait for build to complete** (5-10 minutes)
- [ ] Copy your backend URL (e.g., `https://novahamo-hr-backend.onrender.com`)

### STEP 4️⃣: Update Frontend API Configuration (5 mins)
- [ ] Open `frontend/src/api/index.js`
- [ ] Replace `PROD_URL` with your Render backend URL:
  ```javascript
  const PROD_URL = "https://your-render-backend.onrender.com/api"
  ```
- [ ] Push to GitHub

### STEP 5️⃣: Deploy Frontend to Netlify (10 mins)
- [ ] Sign up at netlify.com with GitHub
- [ ] Click "Add new site" → "Import an existing project"
- [ ] Select GitHub and authorize
- [ ] Select your repository
- [ ] Configure build settings:
  - **Base directory**: `frontend`
  - **Build command**: `npm run build`
  - **Publish directory**: `dist`
- [ ] Add Environment Variable:
  ```
  VITE_API_URL=https://your-render-backend.onrender.com/api
  ```
- [ ] Click "Deploy site"
- [ ] **⏳ Wait for build to complete** (2-5 minutes)
- [ ] Copy your frontend URL (e.g., `https://your-site.netlify.app`)

### STEP 6️⃣: Update Backend CORS Settings (5 mins)
- [ ] Go back to Render dashboard
- [ ] Open your backend service
- [ ] Go to **Environment** section
- [ ] Update `CSRF_TRUSTED_ORIGINS`:
  ```
  https://your-netlify-site.netlify.app,http://localhost:3000
  ```
- [ ] Trigger a redeploy (it will happen automatically)

---

## ✅ Testing Your Deployment

### Backend Health Check
- [ ] Visit: `https://your-render-backend.onrender.com/` (should load without errors)
- [ ] Check logs in Render dashboard for any errors

### Frontend Loading
- [ ] Visit: `https://your-netlify-site.netlify.app`
- [ ] Open browser DevTools (F12) → Console tab
- [ ] Check for CORS or API errors

### Full Integration Test
- [ ] Try to login
- [ ] Navigate to a page that loads data
- [ ] Check that data appears correctly
- [ ] Verify no 404 or 500 errors in console

---

## 🔧 Troubleshooting Quick Fixes

### If Backend won't deploy:
```bash
# Check files exist locally
ls backend/requirements.txt
ls backend/runtime.txt
ls backend/Dockerfile
```

### If Frontend can't reach backend:
1. Open browser console (F12)
2. Check exact error message
3. Verify VITE_API_URL is set correctly in Netlify
4. Verify backend CORS settings include frontend URL

### If MongoDB connection fails:
1. Verify connection string in Render environment variables
2. Check MongoDB Atlas network access includes 0.0.0.0/0
3. Wait 1-2 minutes after updating network access
4. Manually redeploy Render service

---

## 📍 Important URLs to Save

```
Backend API: https://your-render-backend.onrender.com/api
Frontend: https://your-netlify-site.netlify.app
MongoDB Atlas: https://cloud.mongodb.com
Render Dashboard: https://dashboard.render.com
Netlify Dashboard: https://app.netlify.com
```

---

## 🚀 Future Deployments

After initial setup, deployment is automatic:

1. Make changes locally
2. Run tests
3. Commit and push to GitHub:
   ```bash
   git add .
   git commit -m "Your message"
   git push origin main
   ```
4. Both Render and Netlify redeploy automatically
5. Monitor logs in their dashboards

---

**Total Time: ~45-60 minutes for first-time setup**
