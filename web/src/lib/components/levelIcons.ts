import { CircleAlert, CircleCheck, Info, MessageCircle, TriangleAlert } from "@lucide/svelte";

/** Log and toast level → icon. */
export const ICONS = { success: CircleCheck, error: CircleAlert, warning: TriangleAlert, info: Info, chat: MessageCircle };
