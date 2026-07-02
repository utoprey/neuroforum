import { redirect } from 'next/navigation'

/**
 * A topic landing redirects to its articles list, mirroring the legacy
 * UUID-based /topics/<id> page.
 */
export default async function TopicSlugLandingPage({
  params,
}: {
  params: Promise<{ sectionSlug: string; topicSlug: string }>
}) {
  const { sectionSlug, topicSlug } = await params
  redirect(`/sections/${sectionSlug}/topics/${topicSlug}/articles` as never)
}
