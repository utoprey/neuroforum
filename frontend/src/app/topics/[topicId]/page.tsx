import { redirect } from 'next/navigation'

/**
 * Topics are containers for articles; the canonical landing inside a topic
 * is the article list. Redirect /topics/<id> -> /topics/<id>/articles.
 */
export default async function TopicPage({
  params,
}: {
  params: Promise<{ topicId: string }>
}) {
  const { topicId } = await params
  redirect(`/topics/${topicId}/articles`)
}
