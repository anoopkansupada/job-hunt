import { NextRequest, NextResponse } from "next/server"
import { readFile, writeFile, mkdir } from "fs/promises"
import path from "path"

interface ResumeVersion {
  id: string
  name: string
  content: string
  createdAt: string
  isDefault: boolean
}

const DATA_DIR = path.join(process.cwd(), "..", "data")
const RESUMES_FILE = path.join(DATA_DIR, "resumes.json")

async function ensureDataDir() {
  await mkdir(DATA_DIR, { recursive: true })
}

async function loadResumes(): Promise<ResumeVersion[]> {
  try {
    const data = await readFile(RESUMES_FILE, "utf-8")
    return JSON.parse(data)
  } catch {
    return []
  }
}

async function saveResumes(resumes: ResumeVersion[]) {
  await ensureDataDir()
  await writeFile(RESUMES_FILE, JSON.stringify(resumes, null, 2))
}

// GET - list all resumes, or get a specific one by ?id=
export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id")
  const defaultOnly = request.nextUrl.searchParams.get("default")
  const resumes = await loadResumes()

  if (defaultOnly === "true") {
    const defaultResume = resumes.find((r) => r.isDefault)
    return NextResponse.json({ resume: defaultResume || null })
  }

  if (id) {
    const resume = resumes.find((r) => r.id === id)
    if (!resume) {
      return NextResponse.json({ error: "Resume not found" }, { status: 404 })
    }
    return NextResponse.json({ resume })
  }

  // Return list without content for efficiency
  const list = resumes.map(({ content, ...meta }) => meta)
  return NextResponse.json({ resumes: list })
}

// POST - save a new resume version
export async function POST(request: NextRequest) {
  const { name, content } = await request.json()

  if (!name?.trim() || !content?.trim()) {
    return NextResponse.json(
      { error: "Name and content are required" },
      { status: 400 }
    )
  }

  const resumes = await loadResumes()
  const id = `resume_${Date.now()}`
  const isDefault = resumes.length === 0

  const newResume: ResumeVersion = {
    id,
    name: name.trim(),
    content: content.trim(),
    createdAt: new Date().toISOString(),
    isDefault,
  }

  resumes.push(newResume)
  await saveResumes(resumes)

  return NextResponse.json({ resume: { id, name: newResume.name, createdAt: newResume.createdAt, isDefault } })
}

// PUT - update a resume (set default, rename, or update content)
export async function PUT(request: NextRequest) {
  const { id, name, content, setDefault } = await request.json()

  if (!id) {
    return NextResponse.json({ error: "Resume ID is required" }, { status: 400 })
  }

  const resumes = await loadResumes()
  const index = resumes.findIndex((r) => r.id === id)

  if (index === -1) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 })
  }

  if (setDefault) {
    resumes.forEach((r) => (r.isDefault = false))
    resumes[index].isDefault = true
  }
  if (name?.trim()) resumes[index].name = name.trim()
  if (content?.trim()) resumes[index].content = content.trim()

  await saveResumes(resumes)
  return NextResponse.json({ resume: { id, name: resumes[index].name, isDefault: resumes[index].isDefault } })
}

// DELETE - remove a resume version
export async function DELETE(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id")

  if (!id) {
    return NextResponse.json({ error: "Resume ID is required" }, { status: 400 })
  }

  const resumes = await loadResumes()
  const index = resumes.findIndex((r) => r.id === id)

  if (index === -1) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 })
  }

  const wasDefault = resumes[index].isDefault
  resumes.splice(index, 1)

  // If we deleted the default, make the first remaining one default
  if (wasDefault && resumes.length > 0) {
    resumes[0].isDefault = true
  }

  await saveResumes(resumes)
  return NextResponse.json({ success: true })
}
