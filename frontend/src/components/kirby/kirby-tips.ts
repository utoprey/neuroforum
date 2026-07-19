export type KirbyTip = {
  text: string
  href?: string
  hrefLabel?: string
}

const HOME_TIPS: KirbyTip[] = [
  {
    text: 'Держи «Разделы» — там 6 рубрик с новостями, обсуждениями, помощью и флудом.',
    href: '/sections',
    hrefLabel: 'Разделы',
  },
  {
    text: 'Ставлю на то, что тебе интересна нейровизуализация. Загляни в «fMRI и коннектом».',
    href: '/sections/fmri-connectome/topics',
    hrefLabel: 'Открыть раздел',
  },
  {
    text: 'Свежие AI-обзоры авторы прикладывают прямо к статьям — ищи блок «AI обзоры» под текстом.',
  },
]

const SECTIONS_TIPS: KirbyTip[] = [
  {
    text: 'Каждый раздел разбит на 4 категории: новости, обсуждения, помощь, флуд. Табы сверху.',
  },
  {
    text: 'Хочешь свою тему? Нужен раздел, потом кнопка «Создать тему» внутри.',
  },
]

const SECTION_TIPS: KirbyTip[] = [
  {
    text: 'Переключай табы «Новости / Обсуждения / Помощь / Флуд» — контент в каждом свой.',
  },
  {
    text: 'Клик по теме открывает список статей в ней. Внутри можно комментировать с reply-on-selection.',
  },
]

const ARTICLE_TIPS: KirbyTip[] = [
  {
    text: 'Выдели любой фрагмент статьи и нажми «Ответить на выделение» — коммент прикрепится к куску.',
  },
  {
    text: 'LaTeX-формулы рендерятся через KaTeX, code-блоки — с подсветкой. Автор пишет в TipTap.',
  },
  {
    text: 'Автору доступна кнопка «AI обзор» — Claude/GPT дадут резюме или план, оригинал не меняется.',
  },
  {
    text: 'Реакции внизу — 8 нейро-эмодзи: brain, synapse, neuron, microscope, dna, mindblown, petri, lightbulb.',
  },
]

const PROFILE_TIPS: KirbyTip[] = [
  {
    text: 'В профиле — ORCID, соц-ссылки и статистика активности.',
    href: '/me',
    hrefLabel: 'Мой профиль',
  },
  {
    text: 'Хочешь свои LLM-ключи — заходи в «Ключи», добавляй OpenRouter, платформа шифрует их Fernet.',
    href: '/me/credentials',
    hrefLabel: 'Ключи',
  },
]

const CREDENTIALS_TIPS: KirbyTip[] = [
  {
    text: 'Ключ шифруется Fernet-ом под серверным ENCRYPTION_KEY. Мы никогда не отдадим его обратно plaintext.',
  },
  {
    text: 'Можно поставить месячный бюджет в долларах — превышение остановит новые LLM-вызовы.',
  },
  {
    text: 'Рекомендую haiku 4.5 для повседневных AI-обзоров — быстрый и дешёвый.',
  },
]

const DM_TIPS: KirbyTip[] = [
  {
    text: 'Личные сообщения — тот же ProseMirror-редактор, что и в статьях. Можно и LaTeX, и код.',
  },
  {
    text: 'Начать DM — иконка «Написать» на профиле собеседника.',
  },
]

const SAVED_TIPS: KirbyTip[] = [
  {
    text: 'Закладки — то что ты сохранил через кнопку «Сохранить» на статье. Быстрый доступ отсюда.',
  },
]

const DEFAULT_TIPS: KirbyTip[] = [
  {
    text: 'Привет! Клик по мне даст подсказку по текущему экрану.',
  },
  {
    text: 'Если что-то потерял — сверху есть поиск по @-юзерам и статьям.',
  },
]

export function tipsForRoute(pathname: string): KirbyTip[] {
  if (pathname === '/') return HOME_TIPS
  if (pathname === '/sections') return SECTIONS_TIPS
  if (pathname.startsWith('/sections/')) return SECTION_TIPS
  if (pathname.startsWith('/articles/')) return ARTICLE_TIPS
  if (pathname.startsWith('/me/credentials')) return CREDENTIALS_TIPS
  if (pathname.startsWith('/me') || pathname.startsWith('/profile') || pathname.startsWith('/users/')) {
    return PROFILE_TIPS
  }
  if (pathname.startsWith('/dm')) return DM_TIPS
  if (pathname.startsWith('/saved')) return SAVED_TIPS
  return DEFAULT_TIPS
}
