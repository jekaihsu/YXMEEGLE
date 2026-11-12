// Replace '*' with ['pm'] when the owner enables PM-only access.
export const PM_GLANCE_ROLES: readonly string[] = ['*'];
export const pmGlanceVisible = (role: string | undefined, roles = PM_GLANCE_ROLES): boolean =>
 !!role && (roles.includes('*') || roles.includes(role));
