import { NextRequest, NextResponse } from "next/server"

// Since pdf-parse needs Node.js, we'll use a simple fallback
export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData()
    const file = formData.get("file") as File

    if (!file) {
      return NextResponse.json({ error: "No file provided" }, { status: 400 })
    }

    // For now, return error asking to paste text instead
    // Full PDF parsing would require a server library like pdf-parse
    return NextResponse.json(
      { error: "PDF extraction requires server setup. Please paste your resume text instead." },
      { status: 501 }
    )
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Failed to extract PDF" },
      { status: 500 }
    )
  }
}
