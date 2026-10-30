import {useState} from 'react';
import './Avatar.css';

type AvatarPerson = {name: string; department?: string; avatar_url?: string};

function safeAvatar(value?: string): string | undefined {
  if (!value || /[\s\\]/.test(value)) return;
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && !url.username && !url.password && !url.hash && !url.port &&
        (url.hostname === 'feishucdn.com' || url.hostname.endsWith('.feishucdn.com'))) return value;
  } catch {return;}
}

export function Avatar({user, small = false, className}: {user?: AvatarPerson; small?: boolean; className?: string}) {
  const src = safeAvatar(user?.avatar_url);
  const [failed, setFailed] = useState<string>();
  const name = user?.name || '未';
  const colors: Record<string, string> = {'控制組': '#e8edff', '圖資組': '#e8f1ed', '外業組': '#fff0dd', '報告組': '#f4eafa'};
  return <span className={className || `avatar ${small ? 'small' : ''}`} style={{background: colors[user?.department || '']}}>
    {src && failed !== src ? <img key={src} src={src} alt={name} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(src)}/> : name.slice(0, 1)}
  </span>;
}
