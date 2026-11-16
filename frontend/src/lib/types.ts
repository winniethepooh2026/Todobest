export interface User {
  id: string;
  email: string;
  name: string;
  bio: string | null;
  avatar_url: string | null;
  timezone: string;
  has_password: boolean;
  google_connected: boolean;
  is_platform_admin: boolean;
  email_verified: boolean;
  totp_enabled: boolean;
  created_at: string;
}

export type UserSummary = Pick<User, "id" | "name" | "email" | "avatar_url">;

export interface Space {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export type SpaceRole = "owner" | "admin" | "member";

export interface SpaceMember {
  user_id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  role: SpaceRole;
  created_at: string;
}

export interface SpaceMembers {
  current_user_role: SpaceRole;
  can_manage_members: boolean;
  members: SpaceMember[];
}

export type TeamRole = "owner" | "admin" | "member";

export interface TeamMember {
  user_id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  is_active: boolean;
  role: TeamRole;
}

export interface TeamMembers {
  current_user_space_role: SpaceRole;
  current_user_team_role: TeamRole | null;
  can_manage_members: boolean;
  can_manage_owner_role: boolean;
  members: TeamMember[];
}

export interface Invitation {
  id: string;
  space_id: string;
  team_id: string | null;
  email: string | null;
  role: TeamRole;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
  invitation_url?: string;
}

export interface TrashItem {
  kind: "space" | "team" | "board" | "page" | "task";
  id: string;
  name: string;
  deleted_at: string;
}

export interface Team {
  id: string;
  space_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export interface NavigationBoard {
  id: string;
  name: string;
  key: string;
}

export interface NavigationPage {
  id: string;
  title: string;
}

export interface NavigationTeam {
  id: string;
  name: string;
  boards: NavigationBoard[];
  pages: NavigationPage[];
}

export interface NavigationSpace {
  id: string;
  name: string;
  role: SpaceRole;
  teams: NavigationTeam[];
}

export type TaskSystemStatus = "todo" | "in_progress" | "done";
export type TaskPriority = "none" | "low" | "medium" | "high" | "urgent";

export interface TaskLabel {
  id: string;
  name: string;
  color: string;
}

export interface BoardColumn {
  id: string;
  name: string;
  position: number;
  system_status: TaskSystemStatus | null;
  color: string | null;
  is_default: boolean;
}

export interface TaskCard {
  id: string;
  board_id: string;
  status_id: string;
  number: number;
  code: string;
  title: string;
  assignee: UserSummary | null;
  created_by: UserSummary;
  deadline: string | null;
  priority: TaskPriority;
  estimate: number | null;
  parent_task_id: string | null;
  labels: TaskLabel[];
  position: number;
  created_at: string;
  updated_at: string;
}

export interface Task extends TaskCard {
  description: string;
}

export interface TaskComment {
  id: string;
  task_id: string;
  body: string;
  created_by: UserSummary;
  created_at: string;
  updated_at: string;
}

export interface TaskActivity {
  id: string;
  task_id: string;
  actor_id: string | null;
  action: string;
  field: string | null;
  summary: string;
  created_at: string;
}

export type TaskRelationKind = "blocks" | "relates_to" | "duplicates";

export interface TaskRelation {
  id: string;
  source_task_id: string;
  target_task_id: string;
  kind: TaskRelationKind;
  created_at: string;
}

export interface Board {
  id: string;
  team_id: string;
  name: string;
  key: string;
  current_user_id: string;
  can_create_tasks: boolean;
  can_manage_tasks: boolean;
  can_claim_tasks: boolean;
  columns: BoardColumn[];
  tasks: TaskCard[];
  labels: TaskLabel[];
  has_more_by_column: Record<string, boolean>;
  created_at: string;
  updated_at: string;
}

export interface TaskCardPage {
  items: TaskCard[];
  total: number;
  offset: number;
  limit: number;
}

export interface MyTaskPage {
  items: TaskCard[];
  next_cursor: string | null;
}

export interface SearchResult {
  id: string;
  kind: "task" | "page";
  title: string;
  subtitle: string;
  url: string;
  updated_at: string;
}

export interface SearchResponse {
  items: SearchResult[];
  query: string;
}

export interface PageDocument {
  id: string;
  team_id: string;
  title: string;
  content: Record<string, unknown>;
  markdown: string;
  created_by: UserSummary;
  can_edit: boolean;
  can_delete: boolean;
  created_at: string;
  updated_at: string;
}

export interface UploadResult {
  id: string;
  url: string;
  width: number;
  height: number;
  size_bytes: number;
}

export type TodoStatus = "todo" | "in_progress" | "done";

export interface Todo {
  id: string;
  title: string;
  description: string;
  deadline: string | null;
  status: TodoStatus;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface AdminOverview {
  total_users: number;
  new_users_today: number;
  new_users_7d: number;
  new_users_30d: number;
  active_users_24h: number;
  active_users_7d: number;
  active_users_30d: number;
  total_spaces: number;
  total_teams: number;
  total_boards: number;
  total_pages: number;
  total_tasks: number;
}

export interface AdminUser {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  is_platform_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  space_count: number;
  team_count: number;
}

export interface AdminUsersPage {
  items: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminFunnelStep {
  label: string;
  count: number;
}

export interface AdminFunnel {
  steps: AdminFunnelStep[];
}

export interface AdminRegistrationPoint {
  date: string;
  count: number;
}

export interface AdminRegistrations {
  points: AdminRegistrationPoint[];
}

export interface ApiToken {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiTokenCreated extends ApiToken {
  token: string;
}
