import { NextRequest, NextResponse } from "next/server"

export async function POST(request: NextRequest) {
  try {
    const { url } = await request.json()

    if (!url) {
      return NextResponse.json({ error: "No URL provided" }, { status: 400 })
    }

    // Convert Google Docs share URL to export URL
    let exportUrl = url
    if (url.includes("docs.google.com/document")) {
      const docId = url.match(/\/d\/([a-zA-Z0-9-_]+)/)?.[1]
      if (docId) {
        exportUrl = `https://docs.google.com/document/d/${docId}/export?format=txt`
      }
    }

    const response = await fetch(exportUrl)
    if (!response.ok) {
      throw new Error("Failed to fetch Google Docs")
    }

    const text = await response.text()
    return NextResponse.json({ text })
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Failed to fetch Google Docs" },
      { status: 500 }
    )
  }
}
