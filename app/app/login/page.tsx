"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"

export default function LoginPage() {
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const router = useRouter()

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setLoading(true)

    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      })

      const data = await response.json()

      if (response.ok) {
        // Redirect to home on success
        router.push("/")
      } else {
        setError(data.error || "Invalid password")
      }
    } catch (err) {
      setError("Error logging in")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-8">
          <h1 className="text-3xl font-bold text-white text-center mb-2">
            Job Hunt Optimizer
          </h1>
          <p className="text-slate-400 text-center mb-8">
            Resume tailored to any job in seconds
          </p>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-semibold text-white mb-2">
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password..."
                className="w-full px-4 py-2 bg-slate-800 border border-slate-700 text-white rounded-lg focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                autoFocus
              />
            </div>

            {error && (
              <div className="p-3 bg-red-950 border border-red-700 text-red-200 text-sm rounded">
                {error}
              </div>
            )}

            <Button
              type="submit"
              disabled={loading || !password.trim()}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white font-bold py-2 rounded-lg"
            >
              {loading ? "Checking..." : "Enter"}
            </Button>
          </form>

          <p className="text-slate-500 text-xs text-center mt-6">
            Protected app for Catrina's job hunt
          </p>
        </div>
      </div>
    </div>
  )
}
