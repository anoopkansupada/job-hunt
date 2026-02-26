# Deploy to Vercel (5 minutes)

## Step 1: Push to GitHub
```bash
cd /Users/jarvis/.openclaw/workspace/projects/job-hunt/app

# Initialize git (if not already)
git init
git add .
git commit -m "Initial commit: Job Hunt Optimizer"

# Push to GitHub (create repo first at github.com/anoopkansupada/job-hunt)
git remote add origin https://github.com/anoopkansupada/job-hunt.git
git branch -M main
git push -u origin main
```

## Step 2: Connect to Vercel
1. Go to https://vercel.com
2. Click "Add New..." → "Project"
3. Select your GitHub repo (`job-hunt`)
4. Click "Import"

## Step 3: Add Environment Variables
In Vercel dashboard → Settings → Environment Variables:
```
ANTHROPIC_API_KEY = sk-ant-your-key-here
```

## Step 4: Deploy
Click "Deploy" button. Done in ~2 minutes.

---

## You Get
- Live URL: `https://job-hunt.vercel.app` (or custom domain)
- Auto-redeploy on git push
- Vercel handles everything

---

## Share with Catrina
Just send her: `https://job-hunt.vercel.app`

She can use it immediately on any device, anywhere.
