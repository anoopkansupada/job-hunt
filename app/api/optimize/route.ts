import { NextRequest, NextResponse } from "next/server"

const PROMPT_TEMPLATES = {
  tailor: `I'm applying for this job:
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

Output: Show me the revised version I can copy-paste.`,

  audit: `I'm applying for this job:
[JOB_DESCRIPTION]

My current resume:
[RESUME]

Please:
1. Identify gaps between my resume and this JD
2. Score each major requirement (present/missing/weak)
3. Suggest 3-5 specific edits to strengthen my fit
4. Recommend 2 new bullet points based on the job description
5. Check ATS compatibility (keywords, formatting)

Output: A clear gap analysis with specific fixes.`,

  bullet: `For a [ROLE] position, please:
1. Convert my achievements to strong bullet points with quantified results
2. Include specific metrics (numbers, percentages, dollar amounts)
3. Use action verbs that resonate in [INDUSTRY]
4. Format for ATS scanning (clear, scannable, 1-2 lines each)

Resume:
[RESUME]

Job Description:
[JOB_DESCRIPTION]

Output: Revised bullet points I can copy-paste directly into my resume.`,

  cover: `Job posting:
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

Output: Ready-to-personalize draft I can refine.`,

  keywords: `Job description:
[JOB_DESCRIPTION]

My background/resume:
[RESUME]

Please:
1. List the top 10 keywords/phrases from the JD
2. Show where in my resume I'm already hitting those keywords
3. Identify 3-5 keywords I'm missing
4. Suggest bullet points or edits to include those missing keywords
5. Give me an ATS compatibility score (0-100%)

Output: A keyword coverage map showing what I have vs. what I'm missing.`,
}

async function callClaude(resume: string, jobDescription: string, promptType: string): Promise<string> {
  const template = PROMPT_TEMPLATES[promptType as keyof typeof PROMPT_TEMPLATES]
  if (!template) {
    throw new Error("Invalid prompt type")
  }

  const systemPrompt = `You are an expert resume and cover letter coach helping job seekers optimize their applications. 
You provide specific, actionable feedback based on actual job descriptions. 
You focus on quantified achievements, ATS optimization, and keyword matching.
You are direct, clear, and always provide copy-paste-ready output.`

  const userPrompt = template
    .replace("[RESUME]", resume)
    .replace("[JOB_DESCRIPTION]", jobDescription)
    .replace("[ROLE]", jobDescription.split("\n")[0])
    .replace("[INDUSTRY]", "technology")

  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    throw new Error("Claude API key not configured. Set ANTHROPIC_API_KEY in your environment.")
  }

  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: "claude-3-5-sonnet-20241022",
      max_tokens: 1500,
      system: systemPrompt,
      messages: [
        {
          role: "user",
          content: userPrompt,
        },
      ],
    }),
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Claude API error: ${response.statusText}`)
  }

  const data = await response.json()
  return data.content[0]?.text || "No response from Claude"
}

export async function POST(request: NextRequest) {
  try {
    const { resume, jobDescription, promptType } = await request.json()

    if (!resume || !jobDescription || !promptType) {
      return NextResponse.json(
        { error: "Missing required fields" },
        { status: 400 }
      )
    }

    const result = await callClaude(resume, jobDescription, promptType)
    return NextResponse.json({ result })
  } catch (error) {
    console.error("Error:", error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unknown error" },
      { status: 500 }
    )
  }
}
