"use client"

import { useState } from "react"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"

const STRATEGIES = [
  { 
    id: "tailor", 
    name: "Tailor Resume", 
    emoji: "✨",
    description: "Match resume to job, identify gaps, suggest revisions"
  },
  { 
    id: "audit", 
    name: "Audit", 
    emoji: "🔍",
    description: "Score requirements, identify missing keywords, ATS check"
  },
  { 
    id: "bullet", 
    name: "Bullets", 
    emoji: "💫",
    description: "Convert achievements to quantified bullet points"
  },
  { 
    id: "cover", 
    name: "Cover Letter", 
    emoji: "📝",
    description: "Generate role-specific cover letter (3 paragraphs)"
  },
  { 
    id: "keywords", 
    name: "Keywords", 
    emoji: "🎯",
    description: "Map skills to job keywords, find gaps, ATS score"
  },
]

const PROMPTS = {
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

export default function Home() {
  const [resumeSource, setResumeSource] = useState<"text" | "pdf" | "gdocs">("text")
  const [resumeText, setResumeText] = useState("")
  const [resumeFile, setResumeFile] = useState<File | null>(null)
  const [gdocsUrl, setGdocsUrl] = useState("")
  
  const [jobSource, setJobSource] = useState<"text" | "url">("text")
  const [jobText, setJobText] = useState("")
  const [jobUrl, setJobUrl] = useState("")
  
  const [outputs, setOutputs] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [selectedTab, setSelectedTab] = useState("tailor")
  const [showPrompt, setShowPrompt] = useState(false)

  const handleCompareAll = async () => {
    let resume = resumeText
    let jobDesc = jobText

    // Handle resume source
    if (resumeSource === "pdf" && resumeFile) {
      alert("PDF extraction requires paste for now. Please copy-paste the resume text instead.")
      return
    } else if (resumeSource === "gdocs" && gdocsUrl) {
      try {
        const res = await fetch("/api/fetch-gdocs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: gdocsUrl }),
        })
        if (!res.ok) {
          const err = await res.json()
          alert(`Error: ${err.error}`)
          return
        }
        const data = await res.json()
        resume = data.text
      } catch (err) {
        alert("Failed to fetch Google Docs")
        return
      }
    }

    // Handle job source
    if (jobSource === "url" && jobUrl) {
      try {
        const res = await fetch("/api/fetch-url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: jobUrl }),
        })
        if (!res.ok) {
          const err = await res.json()
          alert(`Error: ${err.error}`)
          return
        }
        const data = await res.json()
        jobDesc = data.text
      } catch (err) {
        alert("Failed to fetch job listing")
        return
      }
    }

    if (!resume.trim() || !jobDesc.trim()) {
      alert("Please provide resume and job description")
      return
    }

    setLoading(true)
    setOutputs({})

    // Run all 5 strategies in parallel
    const promises = STRATEGIES.map((strategy) =>
      fetch("/api/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume,
          jobDescription: jobDesc,
          promptType: strategy.id,
        }),
      })
        .then((res) => {
          if (!res.ok) return res.json().then(d => ({ [strategy.id]: `Error: ${d.error}` }))
          return res.json().then((data) => ({ [strategy.id]: data.result || data.error || "No result" }))
        })
        .catch(() => ({ [strategy.id]: "Network error" }))
    )

    const results = await Promise.all(promises)
    const combined = Object.assign({}, ...results)
    setOutputs(combined)
    setSelectedTab("tailor")
    setLoading(false)
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 p-6">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="mb-8 text-center">
          <h1 className="text-5xl font-bold text-white mb-2">Job Hunt Optimizer</h1>
          <p className="text-slate-400">Compare 5 prompting strategies side-by-side</p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Left: Inputs */}
          <div className="space-y-6">
            {/* Resume Section */}
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Resume</h2>
              
              <div className="flex gap-2 mb-4">
                <button
                  onClick={() => setResumeSource("text")}
                  className={`px-3 py-1 rounded text-sm ${resumeSource === "text" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
                >
                  Paste
                </button>
                <button
                  onClick={() => setResumeSource("pdf")}
                  className={`px-3 py-1 rounded text-sm ${resumeSource === "pdf" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
                >
                  PDF
                </button>
                <button
                  onClick={() => setResumeSource("gdocs")}
                  className={`px-3 py-1 rounded text-sm ${resumeSource === "gdocs" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
                >
                  Google Docs
                </button>
              </div>

              {resumeSource === "text" && (
                <Textarea
                  value={resumeText}
                  onChange={(e) => setResumeText(e.target.value)}
                  placeholder="Paste resume..."
                  className="w-full min-h-[180px] bg-slate-800 border-slate-700 text-white rounded p-3 resize-none"
                />
              )}
              {resumeSource === "pdf" && (
                <input
                  type="file"
                  accept=".pdf"
                  onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
                  className="w-full p-3 bg-slate-800 text-white rounded border border-slate-700 cursor-pointer"
                />
              )}
              {resumeSource === "gdocs" && (
                <input
                  type="url"
                  value={gdocsUrl}
                  onChange={(e) => setGdocsUrl(e.target.value)}
                  placeholder="Google Docs share link..."
                  className="w-full p-3 bg-slate-800 text-white rounded border border-slate-700"
                />
              )}
            </div>

            {/* Job Listing Section */}
            <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Job Listing</h2>
              
              <div className="flex gap-2 mb-4">
                <button
                  onClick={() => setJobSource("text")}
                  className={`px-3 py-1 rounded text-sm ${jobSource === "text" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
                >
                  Paste
                </button>
                <button
                  onClick={() => setJobSource("url")}
                  className={`px-3 py-1 rounded text-sm ${jobSource === "url" ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-300"}`}
                >
                  URL
                </button>
              </div>

              {jobSource === "text" && (
                <Textarea
                  value={jobText}
                  onChange={(e) => setJobText(e.target.value)}
                  placeholder="Paste job listing..."
                  className="w-full min-h-[180px] bg-slate-800 border-slate-700 text-white rounded p-3 resize-none"
                />
              )}
              {jobSource === "url" && (
                <input
                  type="url"
                  value={jobUrl}
                  onChange={(e) => setJobUrl(e.target.value)}
                  placeholder="Job posting URL..."
                  className="w-full p-3 bg-slate-800 text-white rounded border border-slate-700"
                />
              )}
            </div>

            {/* Action Button */}
            <Button
              onClick={handleCompareAll}
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white font-bold py-3 rounded-lg"
            >
              {loading ? "Comparing..." : "Compare All Strategies"}
            </Button>
          </div>

          {/* Right: Outputs */}
          <div className="lg:col-span-1">
            {Object.keys(outputs).length > 0 ? (
              <div className="space-y-4">
                <h2 className="text-lg font-semibold text-white">Choose Your Strategy</h2>
                
                {/* Strategy Cards Grid */}
                <div className="space-y-3">
                  {STRATEGIES.map((strategy) => {
                    const output = outputs[strategy.id]
                    const preview = output?.substring(0, 120).replace(/\n/g, " ") + "..."
                    const isSelected = selectedTab === strategy.id

                    return (
                      <div
                        key={strategy.id}
                        onClick={() => {
                          setSelectedTab(strategy.id)
                          setShowPrompt(false)
                        }}
                        className={`p-4 rounded-lg border-2 cursor-pointer transition transform hover:scale-105 ${
                          isSelected
                            ? "border-blue-500 bg-blue-950 shadow-lg shadow-blue-500/20"
                            : "border-slate-700 bg-slate-800 hover:border-slate-600"
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <div className="text-2xl">{strategy.emoji}</div>
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold text-white">{strategy.name}</div>
                            <div className="text-xs text-slate-400 mt-1">{strategy.description}</div>
                            <div className="text-xs text-slate-500 mt-2 line-clamp-2">
                              {preview}
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Detailed View for Selected */}
                {selectedTab && (
                  <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 mt-6">
                    <div className="flex items-center justify-between mb-3">
                      <div>
                        <div className="text-lg font-semibold text-white">
                          {STRATEGIES.find(s => s.id === selectedTab)?.name}
                        </div>
                        <div className="text-xs text-slate-400">
                          {STRATEGIES.find(s => s.id === selectedTab)?.description}
                        </div>
                      </div>
                      <button
                        onClick={() => setShowPrompt(!showPrompt)}
                        className="text-xs px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded"
                      >
                        {showPrompt ? "Output" : "Prompt"}
                      </button>
                    </div>

                    <div className="bg-slate-800 border border-slate-700 rounded p-3 max-h-[350px] overflow-y-auto mb-3">
                      <p className="text-slate-100 whitespace-pre-wrap text-xs leading-relaxed">
                        {showPrompt
                          ? PROMPTS[selectedTab as keyof typeof PROMPTS]
                          : outputs[selectedTab]
                        }
                      </p>
                    </div>

                    <Button
                      onClick={() => {
                        navigator.clipboard.writeText(
                          showPrompt
                            ? PROMPTS[selectedTab as keyof typeof PROMPTS]
                            : outputs[selectedTab]
                        )
                        alert("Copied to clipboard!")
                      }}
                      className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 text-sm rounded"
                    >
                      {showPrompt ? "Copy Prompt" : "Copy Output"}
                    </Button>
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-8 h-full flex items-center justify-center sticky top-6">
                <div className="text-center">
                  <p className="text-slate-400 mb-2">🎯 Ready to compare?</p>
                  <p className="text-slate-500 text-sm">
                    Fill in resume & job, then click "Compare All Strategies"
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
