import { createClient } from "npm:@supabase/supabase-js@2";

const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

function respond(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.serve(async (request) => {
  if (request.method !== "POST") {
    return respond(405, { error: "Method not allowed" });
  }
  if (!supabaseUrl || !serviceRoleKey) {
    return respond(500, { error: "Supabase function secrets are not configured" });
  }

  const authorization = request.headers.get("Authorization");
  const token = authorization?.replace(/^Bearer\s+/i, "");
  if (!token) {
    return respond(401, { error: "Authentication required" });
  }

  const adminClient = createClient(supabaseUrl, serviceRoleKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
  const { data: authData, error: authError } = await adminClient.auth.getUser(token);
  if (authError || !authData.user) {
    return respond(401, { error: "Invalid or revoked session" });
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return respond(400, { error: "Invalid JSON request body" });
  }

  const { data: adminRecord, error: adminError } = await adminClient
    .from("app_admins")
    .select("user_id")
    .eq("user_id", authData.user.id)
    .maybeSingle();
  if (adminError) {
    return respond(500, { error: "Could not verify administrator permissions" });
  }

  if (body.action === "status") {
    return respond(200, { is_admin: Boolean(adminRecord) });
  }
  if (!adminRecord) {
    return respond(403, { error: "Administrator permission required" });
  }

  if (body.action === "list") {
    const users = [];
    for (let page = 1; ; page += 1) {
      const { data, error } = await adminClient.auth.admin.listUsers({ page, perPage: 1000 });
      if (error) {
        return respond(400, { error: error.message });
      }
      users.push(
        ...data.users.map((user) => ({
          id: user.id,
          email: user.email,
          created_at: user.created_at,
          last_sign_in_at: user.last_sign_in_at,
        })),
      );
      if (data.users.length < 1000) {
        break;
      }
    }
    return respond(200, { users });
  }

  if (body.action === "create") {
    const email = typeof body.email === "string" ? body.email.trim() : "";
    const password = typeof body.password === "string" ? body.password : "";
    if (!email || password.length < 8) {
      return respond(400, { error: "A valid email and a password of at least 8 characters are required" });
    }
    const { data, error } = await adminClient.auth.admin.createUser({
      email,
      password,
      email_confirm: true,
    });
    if (error) {
      return respond(400, { error: error.message });
    }
    return respond(201, {
      user: { id: data.user.id, email: data.user.email, created_at: data.user.created_at },
    });
  }

  if (body.action === "delete") {
    const userId = typeof body.user_id === "string" ? body.user_id : "";
    if (!userId || userId === authData.user.id) {
      return respond(400, { error: "Choose another user to delete" });
    }
    const { data: targetAdmin, error: targetAdminError } = await adminClient
      .from("app_admins")
      .select("user_id")
      .eq("user_id", userId)
      .maybeSingle();
    if (targetAdminError) {
      return respond(500, { error: "Could not verify target user permissions" });
    }
    if (targetAdmin) {
      return respond(403, { error: "Administrator accounts cannot be deleted here" });
    }
    const { error } = await adminClient.auth.admin.deleteUser(userId);
    if (error) {
      return respond(400, { error: error.message });
    }
    return respond(200, { deleted: true });
  }

  return respond(400, { error: "Unsupported action" });
});
