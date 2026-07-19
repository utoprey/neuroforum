/**
 * Wire-shape TypeScript types mirroring backend Pydantic schemas in
 * backend/app/modules/[module]/schemas.py. Keep in sync by hand for now;
 * a future round can generate them from OpenAPI.
 */

export type UserRole = 'user' | 'moderator' | 'admin' | 'agent'

export type ArticleStatus = 'draft' | 'published' | 'archived' | 'hidden'

export type TopicKind = 'news' | 'discussion' | 'help' | 'flood'

export const TOPIC_KINDS: TopicKind[] = ['news', 'discussion', 'help', 'flood']

export const TOPIC_KIND_LABEL: Record<TopicKind, string> = {
  news: 'Новости и статьи',
  discussion: 'Обсуждения',
  help: 'Помощь',
  flood: 'Флуд',
}

export type MessageStatus =
  | 'visible'
  | 'edited'
  | 'hidden_by_mod'
  | 'deleted_by_author'

export type ReactionKind =
  | 'brain'
  | 'synapse'
  | 'neuron'
  | 'microscope'
  | 'dna'
  | 'mindblown'
  | 'petri'
  | 'lightbulb'

export const REACTION_KINDS: ReactionKind[] = [
  'brain',
  'synapse',
  'neuron',
  'microscope',
  'dna',
  'mindblown',
  'petri',
  'lightbulb',
]

export const REACTION_GLYPH: Record<ReactionKind, string> = {
  brain: '🧠',
  synapse: '⚡',
  neuron: '🪩',
  microscope: '🔬',
  dna: '🧬',
  mindblown: '🤯',
  petri: '🧫',
  lightbulb: '💡',
}

export interface ProfileRead {
  display_name: string | null
  bio: string | null
  avatar_url: string | null
  orcid: string | null
  social_links: Record<string, string>
  locale: string
  timezone: string
}

export interface StatsRead {
  articles_count: number
  messages_count: number
  received_reactions_count: number
  saved_articles_count: number
  updated_at: string | null
}

export interface UserRead {
  id: string
  username: string
  email: string | null
  role: UserRole
  is_active: boolean
  created_at: string
  profile: ProfileRead | null
  stats: StatsRead | null
  is_online?: boolean
  last_seen_at?: string | null
}

export interface UserPublic {
  id: string
  username: string
  display_name: string | null
  avatar_url: string | null
  role: UserRole
  is_online?: boolean
  last_seen_at?: string | null
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export interface SectionRead {
  id: string
  slug: string
  title: string
  description: string | null
  position: number
  icon: string | null
  created_at: string
  updated_at: string
}

export interface TopicRead {
  id: string
  section_id: string
  /** Slug of the parent section. Mirrors backend ``TopicRead.section_slug``.
   * Used by the frontend to build canonical
   * ``/sections/<section_slug>/topics/<topic_slug>`` URLs without a second
   * round-trip per topic card. */
  section_slug: string
  slug: string
  title: string
  description: string | null
  is_locked: boolean
  is_pinned: boolean
  kind: TopicKind
  created_by: UserPublic
  created_at: string
  updated_at: string
}

/** ProseMirror "doc" — fed to TipTap as JSONContent. Loosely typed: the
 * wire shape is a discriminated union of block kinds and we don't want to
 * enumerate them on the frontend. Matches TipTap's `JSONContent`. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type DocContent = { type?: string; [key: string]: any }

export interface ArticleRead {
  id: string
  topic_id: string
  slug: string
  title: string
  summary: string | null
  content: DocContent
  author: UserPublic
  status: ArticleStatus
  published_at: string | null
  view_count: number
  comment_count: number
  mentioned_user_ids: string[]
  reaction_counts: Partial<Record<ReactionKind, number>>
  created_at: string
  updated_at: string
}

export interface ArticlePublic {
  id: string
  slug: string
  topic_id: string
  title: string
  summary: string | null
  author: UserPublic
  status: ArticleStatus
  published_at: string | null
  view_count: number
  comment_count: number
  reaction_counts: Partial<Record<ReactionKind, number>>
}

export interface ReplyToSelection {
  target: { type: 'article' | 'message'; id: string }
  block_path: number[]
  from: number
  to: number
  quote_text: string
}

export interface MessageRead {
  id: string
  article_id: string
  parent_id: string | null
  thread_root_id: string | null
  depth: number
  path: string
  author: UserPublic
  content: DocContent | null
  placeholder: string | null
  status: MessageStatus
  reply_to_selection: ReplyToSelection | null
  mentioned_user_ids: string[]
  reaction_counts: Partial<Record<ReactionKind, number>>
  created_at: string
  updated_at: string
}

export interface ReactionSummary {
  kind: ReactionKind
  count: number
}

export interface NotificationRead {
  id: string
  type: string
  payload: Record<string, unknown>
  is_read: boolean
  created_at: string
}

export interface UnifiedSearchResult {
  articles: { article: ArticlePublic; rank: number; snippet: string }[]
  messages: {
    message_id: string
    article_id: string
    snippet: string
    rank: number
  }[]
  users: UserPublic[]
}

export interface RecentTopic {
  id: string
  slug: string
  title: string
  last_message_at: string | null
}

export interface RecentMessage {
  id: string
  article_id: string
  article_title: string
  article_slug: string
  topic_id: string
  topic_slug: string
  snippet: string
  created_at: string
}

export interface SavedArticleRead {
  article_id: string
  saved_at: string
  article: ArticlePublic
}

/** Single row in the public "reactions left by user" feed (GET /users/{username}/reactions). */
export interface UserReactionItem {
  target_type: 'article' | 'message'
  target_id: string
  kind: ReactionKind
  reacted_at: string
  article_id: string
  article_slug: string
  article_title: string
  snippet: string
}

// ---------------------------------------------------------------------------
// DM / conversations
// ---------------------------------------------------------------------------

export type ConversationKind = 'dm' | 'group'

export type DirectMessageStatus =
  | 'visible'
  | 'edited'
  | 'deleted_by_author'
  | 'hidden_by_mod'

export interface ConversationRead {
  id: string
  kind: ConversationKind
  title: string | null
  participants: UserPublic[]
  last_message_at: string | null
  unread_count: number
}

export interface DirectMessageRead {
  id: string
  conversation_id: string
  author: UserPublic
  content: DocContent | null
  placeholder: string | null
  reply_to_id: string | null
  status: DirectMessageStatus
  attachments: string[]
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Attachments
// ---------------------------------------------------------------------------

export type AttachmentKind = 'image' | 'gif' | 'video' | 'file'

export type AttachmentProcessingStatus = 'pending' | 'ready' | 'failed'

export interface AttachmentKindLimits {
  kind: AttachmentKind
  max_bytes: number
  max_mb: number
  allowed_mime_types: string[]
}

export interface AttachmentLimits {
  kinds: AttachmentKindLimits[]
}

export interface AttachmentUploadResponse {
  attachment_id: string
  upload_url: string
  upload_method: string
  expires_in_sec: number
  object_key: string
  headers: Record<string, string>
}

export interface AttachmentRead {
  id: string
  kind: AttachmentKind
  mime_type: string
  size_bytes: number
  width: number | null
  height: number | null
  duration_sec: number | null
  processing_status: AttachmentProcessingStatus
  url: string
  poster_url: string | null
  created_at: string
}

// ---------------------------------------------------------------------------
// AI proposals + article revisions
// ---------------------------------------------------------------------------

export type AIProposalAction =
  | 'draft'
  | 'expand'
  | 'rephrase'
  | 'summarize'
  | 'cite_check'
  | 'translate'
  | 'outline'

export type AIProposalStatus = 'pending' | 'accepted' | 'rejected' | 'expired'

export const AI_PROPOSAL_ACTION_LABEL: Record<AIProposalAction, string> = {
  draft: 'Черновик с нуля',
  expand: 'Расширить раздел',
  rephrase: 'Перефразировать',
  summarize: 'Сделать резюме',
  cite_check: 'Проверить ссылки/цитаты',
  translate: 'Перевести',
  outline: 'Составить план',
}

export const AI_PROPOSAL_ACTIONS: AIProposalAction[] = [
  'draft',
  'expand',
  'rephrase',
  'summarize',
  'cite_check',
  'translate',
  'outline',
]

export interface AIProposalSelection {
  block_path: number[]
  from: number
  to: number
}

export interface ArticleAIProposal {
  id: string
  article_id: string
  requested_by: UserPublic
  agent: UserPublic | null
  action: AIProposalAction
  selection: AIProposalSelection | null
  prompt: string | null
  proposed_content: DocContent
  status: AIProposalStatus
  decided_by: UserPublic | null
  decided_at: string | null
  created_at: string
  expires_at: string
}

export interface ArticleRevisionRead {
  id: string
  revision: number
  editor: UserPublic
  editor_role_at_edit: string
  title: string
  content: DocContent
  edit_reason: string | null
  created_at: string
}

export type LLMProvider = 'openrouter' | 'cloud_ru' | 'anthropic_direct' | 'openai_direct'

export const LLM_PROVIDER_LABEL: Record<LLMProvider, string> = {
  openrouter: 'OpenRouter',
  cloud_ru: 'Cloud.ru (заглушка)',
  anthropic_direct: 'Anthropic (direct)',
  openai_direct: 'OpenAI (direct)',
}

export interface AgentCredentialRead {
  id: string
  provider: LLMProvider
  display_name: string
  key_fingerprint: string
  default_model: string | null
  is_active: boolean
  monthly_budget_usd: string | null
  spent_this_month: string
  created_at: string
  last_used_at: string | null
}

export interface AgentCredentialCreate {
  provider: LLMProvider
  display_name: string
  api_key: string
  default_model?: string
  monthly_budget_usd?: string
}
