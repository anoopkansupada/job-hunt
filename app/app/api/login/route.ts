import { NextRequest, NextResponse } from "next/server"

export async function POST(request: NextRequest) {
  try {
    const { password } = await request.json()

    if (!password) {
      return NextResponse.json(
        { error: "Password required" },
        { status: 400 }
      )
    }

    // Get password from environment variable
    const correctPassword = process.env.JOB_HUNT_PASSWORD

    if (!correctPassword) {
      return NextResponse.json(
        { error: "Server not configured" },
        { status: 500 }
      )
    }

    if (password !== correctPassword) {
      return NextResponse.json(
        { error: "Invalid password" },
        { status: 401 }
      )
    }

    // Create response with auth cookie
    const response = NextResponse.json({ success: true })
    response.cookies.set("job-hunt-auth", "authenticated", {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 30, // 30 days
    })

    return response
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Login failed" },
      { status: 500 }
    )
  }
}
