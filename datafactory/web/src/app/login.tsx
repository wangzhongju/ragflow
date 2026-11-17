import { useState, type FormEvent } from "react";
import { Base64 } from "js-base64";
import JSEncrypt from "jsencrypt";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import RagflowMark from "./ragflow-mark.svg";
import "./login.css";

const RagflowPublicKey =
  "-----BEGIN PUBLIC KEY-----MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArq9XTUSeYr2+N1h3Afl/z8Dse/2yD0ZGrKwx+EEEcdsBLca9Ynmx3nIB5obmLlSfmskLpBo0UACBmB5rEjBp2Q2f3AG3Hjd4B+gNCG6BDaawuDlgANIhGnaTLrIqWrrcm4EMzJOnAOI1fgzJRsOOUEfaS318Eq9OVO3apEyCCt0lOQK6PuksduOjVxtltDav+guVAA068NrPYmRNabVKRNLJpL8w4D44sfth5RvZ3q9t+6RTArpEtc5sh5ChzvqPOzKGMXW83C95TxmXqpbK6olN4RevSfVjEAgCydH6HN6OhtOQEcnrU97r9H0iZOWwbw3pVrZiUkuRD1R56Wzs2wIDAQAB-----END PUBLIC KEY-----";

function encryptPassword(password: string): string {
  const encryptor = new JSEncrypt();
  encryptor.setPublicKey(RagflowPublicKey);
  return encryptor.encrypt(Base64.encode(password)) || "";
}

export function Login() {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setShowPassword(false);
    try {
      await api.login({
        email: String(data.get("email")),
        password: encryptPassword(String(data.get("password"))),
      });
      navigate("/projects");
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "invalid_credentials"
          ? "invalidCredentials"
          : "loginUnavailable",
      );
    } finally {
      setBusy(false);
    }
  }

  function handleTogglePassword() {
    setShowPassword((visible) => !visible);
  }

  return (
    <main
      className="sign-in"
      aria-labelledby="sign-in-product"
      lang={i18n.resolvedLanguage}
    >
      <svg
        className="sign-in-traces"
        viewBox="0 0 1440 720"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path
          d="M1282.81 -45L999.839 147.611C988.681 155.206 975.496 159.267 961.999 159.267H330.429C317.253 159.267 304.368 155.397 293.373 148.137L0.88623 -45"
          transform="translate(40 0)"
        />
        <path
          d="M0 1L203.392 203.181C215.992 215.705 233.036 222.736 250.802 222.736H287.103C305.94 222.736 323.913 230.636 336.649 244.514L425.401 341.222C438.137 355.1 456.11 363 474.947 363H976.902C996.333 363 1014.81 354.595 1027.59 339.95L1104.79 251.424C1116.14 238.4 1132.08 230.248 1149.29 228.659L1191.13 224.796C1205.62 223.458 1219.28 217.461 1230.06 207.704L1440 17.7981"
          transform="translate(0 48)"
        />
        <path
          d="M-10 1L57.1932 71.1509C67.7929 82.2171 74.2953 96.5714 75.6239 111.837L79.8042 159.87C81.3312 177.416 89.68 193.662 103.057 205.117L399.311 458.829C411.497 469.265 427.011 475 443.054 475H972.606C988.463 475 1003.81 469.396 1015.94 459.179L1310.78 210.75C1323.01 200.451 1331.16 186.136 1333.79 170.369L1341.87 121.837C1344.06 108.691 1350.11 96.492 1359.24 86.7885L1440 1"
          transform="translate(0 226)"
        />
      </svg>
      <header className="sign-in-brand">
        <img src={RagflowMark} alt="" width={32} height={32} />
        <strong>DataFactory</strong>
      </header>
      <h1 id="sign-in-product">{t("loginProductTitle")}</h1>
      <section className="sign-in-panel">
        <h2 id="sign-in-title">{t("loginTitle")}</h2>
        <p id="sign-in-hint">{t("loginHint")}</p>
        <form
          className="sign-in-card"
          aria-labelledby="sign-in-title"
          aria-describedby="sign-in-hint"
          aria-busy={busy}
          onSubmit={handleSubmit}
        >
          <div className="sign-in-field">
            <label htmlFor="sign-in-email">
              <span aria-hidden="true">* </span>
              {t("loginEmail")}
            </label>
            <input
              id="sign-in-email"
              name="email"
              type="email"
              autoComplete="username"
              placeholder={t("loginEmailPlaceholder")}
              required
            />
          </div>
          <div className="sign-in-field">
            <label htmlFor="sign-in-password">
              <span aria-hidden="true">* </span>
              {t("loginPassword")}
            </label>
            <div className="sign-in-password">
              <input
                id="sign-in-password"
                name="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                placeholder={t("loginPasswordPlaceholder")}
                required
              />
              <button
                type="button"
                aria-controls="sign-in-password"
                aria-label={t(
                  showPassword ? "loginHidePassword" : "loginShowPassword",
                )}
                onClick={handleTogglePassword}
              >
                <svg
                  viewBox="0 0 24 24"
                  width={18}
                  height={18}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z" />
                  <circle cx="12" cy="12" r="2.5" />
                  {showPassword && <path d="m3 3 18 18" />}
                </svg>
              </button>
            </div>
          </div>
          {error && (
            <p className="sign-in-error" role="alert">
              {t(error)}
            </p>
          )}
          <button className="sign-in-submit" type="submit" disabled={busy}>
            {busy ? t("loginSubmitting") : t("loginSubmit")}
          </button>
        </form>
      </section>
    </main>
  );
}
