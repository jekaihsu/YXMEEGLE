export function buildLabel(health:unknown):string {
 if(!health || typeof health!=='object' || !('build' in health))return '版本未知';
 const build=health.build;
 if(!build || typeof build!=='object' || !('git_sha' in build) || typeof build.git_sha!=='string' || !/^[0-9a-f]{40}$/.test(build.git_sha) || !('dirty' in build) || typeof build.dirty!=='boolean')return '版本未知';
 return `版本 ${build.git_sha.slice(0,7)}${build.dirty?' · 含未提交變更':''}`;
}
