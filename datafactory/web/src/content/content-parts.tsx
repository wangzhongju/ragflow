import DOMPurify from "dompurify";
import { useTranslation } from "react-i18next";
import { assetUrl, type ContentPart } from "../api/client";

export function ContentParts({
  parts,
  loading = false,
  error,
}: {
  parts: ContentPart[];
  loading?: boolean;
  error?: string;
}) {
  const { t } = useTranslation();
  if (loading) return <p aria-busy="true">{t("loading")}</p>;
  if (error) return <p role="alert">{error}</p>;
  if (parts.length === 0) return <p>{t("noContent")}</p>;
  return (
    <div className="content-parts">
      {parts.map((part, index) => {
        if (part.type === "image" && part.asset_id)
          return (
            <figure key={index} style={{ margin: 0 }}>
              <img
                loading="lazy"
                src={assetUrl(part.asset_id)}
                alt={part.text || t("sourceImage")}
                style={{
                  maxWidth: "100%",
                  maxHeight: 500,
                  objectFit: "contain",
                  width: "100%",
                  aspectRatio: "4 / 3",
                }}
              />
              <figcaption>
                {part.region?.page != null &&
                  `${t("pageNumber")} ${part.region.page}`}
              </figcaption>
            </figure>
          );
        if (part.type === "table" && part.html)
          return (
            <div
              key={index}
              dangerouslySetInnerHTML={{
                __html: DOMPurify.sanitize(part.html, {
                  ALLOWED_TAGS: [
                    "table",
                    "thead",
                    "tbody",
                    "tr",
                    "td",
                    "th",
                    "caption",
                    "p",
                    "br",
                    "strong",
                  ],
                  ALLOWED_ATTR: ["colspan", "rowspan"],
                }),
              }}
            />
          );
        if (part.type === "audio" && part.asset_id)
          return (
            <audio
              key={index}
              controls
              preload="metadata"
              src={assetUrl(part.asset_id)}
            />
          );
        if (part.type === "video" && part.asset_id)
          return (
            <video
              key={index}
              controls
              preload="metadata"
              src={assetUrl(part.asset_id)}
              style={{ maxWidth: "100%" }}
            />
          );
        return (
          <p
            key={index}
            style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
          >
            {part.text}
          </p>
        );
      })}
    </div>
  );
}
