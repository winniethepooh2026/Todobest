import { ImageResponse } from "next/og";

export const alt = "Noki — задачи и знания команды в одном месте";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        flexDirection: "column",
        justifyContent: "center",
        padding: 88,
        color: "#fafafa",
        background: "linear-gradient(135deg, #171717 0%, #26235c 100%)",
      }}
    >
      <div style={{ display: "flex", fontSize: 38, fontWeight: 700 }}>Noki</div>
      <div
        style={{
          display: "flex",
          marginTop: 55,
          fontSize: 66,
          fontWeight: 700,
        }}
      >
        Задачи и знания команды
      </div>
      <div
        style={{
          display: "flex",
          marginTop: 20,
          fontSize: 32,
          color: "#d4d4d8",
        }}
      >
        В одном понятном пространстве
      </div>
    </div>,
    size,
  );
}
