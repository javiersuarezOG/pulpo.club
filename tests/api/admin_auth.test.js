// Unit tests for api/_admin_auth.js — the shared bearer-token gate
// applied to every /api/admin/* endpoint. Constant-time match,
// graceful 503 when env is unset, 401 otherwise.

import { describe, it, expect, beforeEach } from "vitest";
import {
  requireAdminAuth,
  readBearerToken,
  tokensMatch,
  ENV_NAME,
} from "../../api/_admin_auth.js";

function mockReq(headers = {}) {
  return { headers };
}

function mockRes() {
  const res = {
    statusCode: 200,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(payload)  { this.body = payload; return this; },
  };
  return res;
}

beforeEach(() => {
  process.env[ENV_NAME] = "the-correct-token";
});

describe("readBearerToken", () => {
  it("returns the token from a Bearer header", () => {
    expect(readBearerToken(mockReq({ authorization: "Bearer abc123" }))).toBe("abc123");
  });

  it("returns empty string when header absent", () => {
    expect(readBearerToken(mockReq())).toBe("");
  });

  it("returns empty string for non-Bearer schemes", () => {
    expect(readBearerToken(mockReq({ authorization: "Basic abc123" }))).toBe("");
  });

  it("trims trailing whitespace from the token", () => {
    expect(readBearerToken(mockReq({ authorization: "Bearer abc123  " }))).toBe("abc123");
  });
});

describe("tokensMatch", () => {
  it("returns true on identical tokens", () => {
    expect(tokensMatch("abc", "abc")).toBe(true);
  });

  it("returns false on different tokens", () => {
    expect(tokensMatch("abc", "abcd")).toBe(false);
    expect(tokensMatch("abc", "xyz")).toBe(false);
  });

  it("returns false when either side is empty", () => {
    expect(tokensMatch("", "abc")).toBe(false);
    expect(tokensMatch("abc", "")).toBe(false);
    expect(tokensMatch("", "")).toBe(false);
  });
});

describe("requireAdminAuth", () => {
  it("returns true + leaves res untouched on a valid token", () => {
    const req = mockReq({ authorization: "Bearer the-correct-token" });
    const res = mockRes();
    expect(requireAdminAuth(req, res)).toBe(true);
    expect(res.statusCode).toBe(200); // unchanged
    expect(res.body).toBeNull();
  });

  it("sends 401 + returns false on a wrong token", () => {
    const req = mockReq({ authorization: "Bearer wrong" });
    const res = mockRes();
    expect(requireAdminAuth(req, res)).toBe(false);
    expect(res.statusCode).toBe(401);
    expect(res.body.error).toBe("unauthorized");
  });

  it("sends 401 when no Authorization header is present", () => {
    const req = mockReq();
    const res = mockRes();
    expect(requireAdminAuth(req, res)).toBe(false);
    expect(res.statusCode).toBe(401);
  });

  it("sends 503 (not 401) when PULPO_ADMIN_DEBUG_TOKEN env is unset", () => {
    delete process.env[ENV_NAME];
    const req = mockReq({ authorization: "Bearer anything" });
    const res = mockRes();
    expect(requireAdminAuth(req, res)).toBe(false);
    expect(res.statusCode).toBe(503);
    expect(res.body.error).toBe("admin_not_configured");
  });

  it("is case-sensitive on the token value", () => {
    const req = mockReq({ authorization: "Bearer THE-CORRECT-TOKEN" });
    const res = mockRes();
    expect(requireAdminAuth(req, res)).toBe(false);
    expect(res.statusCode).toBe(401);
  });
});
