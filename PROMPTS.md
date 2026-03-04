# Job Hunt — 5 Super Prompts

Extracted from `app/api/optimize/route.ts` (Feb 26, 2026). Use these anywhere: agents, LLM calls, other tools.

Replace `[RESUME]`, `[JOB_DESCRIPTION]`, `[ROLE]`, `[INDUSTRY]` with actual content.

---

## 1. TAILOR

I'm applying for this job:
[JOB_DESCRIPTION]

My current resume:
[RESUME]

Please:
1. Identify 3-5 gaps between my resume and this JD
2. Rewrite my 3 weakest bullet points to include:
   - Specific metrics/results (e.g., "increased by X%", "saved $Y")
   - Keywords from the job description
   - Action verbs (led, launched, optimized, scaled)
3. Suggest 2 new bullet points I should add based on the JD
4. Optimize my professional summary for ATS (use keywords, active language)

Output: Show me the revised version I can copy-paste.

---

## 2. AUDIT

I'm applying for this job:
[JOB_DESCRIPTION]

My current resume:
[RESUME]

Please:
1. Identify gaps between my resume and this JD
2. Score each major requirement (present/missing/weak)
3. Suggest 3-5 specific edits to strengthen my fit
4. Recommend 2 new bullet points based on the job description
5. Check ATS compatibility (keywords, formatting)

Output: A clear gap analysis with specific fixes.

---

## 3. BULLET

For a [ROLE] position, please:
1. Convert my achievements to strong bullet points with quantified results
2. Include specific metrics (numbers, percentages, dollar amounts)
3. Use action verbs that resonate in [INDUSTRY]
4. Format for ATS scanning (clear, scannable, 1-2 lines each)

Resume:
[RESUME]

Job Description:
[JOB_DESCRIPTION]

Output: Revised bullet points I can copy-paste directly into my resume.

---

## 4. COVER

Job posting:
[JOB_DESCRIPTION]

My background:
[RESUME]

Please write a 3-paragraph cover letter that:
1. Opens with a specific insight about the company/role (not generic)
2. Maps my top 3 skills to their top 3 requirements
3. Ends with a specific call to action
4. Uses confident, active language
5. Stays under 250 words
6. Includes 2-3 keywords from the job description naturally

Output: Ready-to-personalize draft I can refine.

---

## 5. KEYWORDS

Job description:
[JOB_DESCRIPTION]

My background/resume:
[RESUME]

Please:
1. List the top 10 keywords/phrases from the JD
2. Show where in my resume I'm already hitting those keywords
3. Identify 3-5 keywords I'm missing
4. Suggest bullet points or edits to include those missing keywords
5. Give me an ATS compatibility score (0-100%)

Output: A keyword coverage map showing what I have vs. what I'm missing.

---

## System Context (For Claude)

Use this alongside any of the prompts above to set tone/expectations:

> You are an expert resume and cover letter coach helping job seekers optimize their applications. You provide specific, actionable feedback based on actual job descriptions. You focus on quantified achievements, ATS optimization, and keyword matching. You are direct, clear, and always provide copy-paste-ready output.

---

## Usage Examples

**In a Slack agent:** Load this file as system context, call with prompt type + inputs  
**In a script:** Use as template for jinja2/string replacement  
**In another LLM:** Copy any section directly into your prompt  
**In a config:** Reference as `projects/job-hunt/PROMPTS.md#{PROMPT_NAME}`
