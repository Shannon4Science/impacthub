import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, type Milestone, type UserProfile } from "@/lib/api";
import MilestoneCard from "@/components/MilestoneCard";
import { ArrowLeft, Trophy, Loader2 } from "lucide-react";

export default function MilestonePage() {
  const { id } = useParams<{ id: string }>();
  const userId = id || "";

  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.getMilestones(userId), api.getProfile(userId)])
      .then(([ms, p]) => {
        setMilestones(ms);
        setUser(p.user);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [userId]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-indigo-500" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-gray-400">
        未找到该用户。
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-white to-orange-50">
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="mb-8 flex items-center justify-between">
          <Link
            to={`/profile/${userId}`}
            className="flex items-center gap-1.5 text-sm text-gray-400 transition hover:text-gray-600"
          >
            <ArrowLeft className="h-4 w-4" />
            返回主页
          </Link>
        </div>

        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-amber-100 px-4 py-1.5 text-sm font-medium text-amber-700">
            <Trophy className="h-4 w-4" />
            里程碑
          </div>
          <h1 className="text-3xl font-bold text-gray-900">
            {user.name} 的成就
          </h1>
          <p className="mt-2 text-gray-500">
            已达成 {milestones.length} 个里程碑
          </p>
        </div>

        {milestones.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-gray-300 bg-white py-16 text-center">
            <Trophy className="mx-auto h-12 w-12 text-gray-300" />
            <p className="mt-3 text-gray-400">
              暂无里程碑，继续加油！
            </p>
          </div>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2">
            {milestones.map((ms) => (
              <MilestoneCard key={ms.id} milestone={ms} user={user} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
