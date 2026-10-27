import { useState, type ReactNode } from 'react';
import { copy, localizedName } from '../i18n';
import type { Language, Metadata, Moment, Tracking } from '../types';

export function Pitch({
  metadata,
  frame,
  clock,
  selected,
  language,
  moments,
  onSelect,
  layers,
}: {
  metadata: Metadata;
  frame: Tracking | null;
  clock: number;
  selected: string;
  language: Language;
  moments: Moment[];
  onSelect: (id: string) => void;
  layers?: ReactNode;
}) {
  const [names, setNames] = useState(false);
  const players = new Map(
    [...metadata.home.players, ...metadata.away.players].map((p) => [p.player_id, p]),
  );
  const badges = moments.filter(
    (m) => m.type === 'player_milestone' && m.game_clock_s <= clock && clock < m.game_clock_s + 12,
  );
  return (
    <div className="pitch-wrap">
      <svg
        className="pitch"
        viewBox="-3 -4 111 76"
        role="group"
        aria-label={
          language === 'ar'
            ? 'مواقع اللاعبين والكرة من بث المباراة'
            : 'Player and ball positions from the match stream'
        }
        direction="ltr"
      >
        <title>
          {metadata.home.name} vs {metadata.away.name}
        </title>
        <defs>
          <pattern id="grass" width="21" height="68" patternUnits="userSpaceOnUse">
            <rect width="10.5" height="68" fill="var(--grass-light)" />
            <rect x="10.5" width="10.5" height="68" fill="var(--grass-dark)" />
          </pattern>
        </defs>
        <rect width="105" height="68" rx=".4" fill="url(#grass)" />
        <g fill="none" stroke="var(--pitch-line)" strokeWidth=".22">
          <rect width="105" height="68" />
          <path d="M52.5 0V68" />
          <circle cx="52.5" cy="34" r="9.15" />
          <path d="M0 13.84H16.5V54.16H0M105 13.84H88.5V54.16H105M0 24.84H5.5V43.16H0M105 24.84H99.5V43.16H105" />
          <path d="M16.5 26.7Q24.5 34 16.5 41.3M88.5 26.7Q80.5 34 88.5 41.3" />
          <rect x="-2" y="30.34" width="2" height="7.32" />
          <rect x="105" y="30.34" width="2" height="7.32" />
        </g>
        <g fill="var(--pitch-line)">
          <circle cx="52.5" cy="34" r=".35" />
          <circle cx="11" cy="34" r=".25" />
          <circle cx="94" cy="34" r=".25" />
        </g>
        {layers}
        {frame?.players.map(([id, x, y]) => {
          const player = players.get(id);
          if (!player) return null;
          const team = player.team_id === metadata.home.team_id ? metadata.home : metadata.away;
          const active = id === selected;
          const badge = badges.find((m) => m.player_id === id)?.verified_facts.badge;
          return (
            <g
              key={id}
              className="pitch-player"
              role="button"
              tabIndex={0}
              aria-label={localizedName(player, language)}
              aria-pressed={active}
              onClick={() => onSelect(id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  onSelect(id);
                }
              }}
            >
              <title>
                {localizedName(player, language)} · {player.shirt_number}
              </title>
              {active && (
                <circle
                  cx={x}
                  cy={68 - y}
                  r="2.8"
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth=".45"
                />
              )}
              <circle
                cx={x}
                cy={68 - y}
                r="1.9"
                fill={team.primary_color}
                stroke="white"
                strokeWidth=".35"
              />
              <text
                x={x}
                y={68 - y + 0.6}
                textAnchor="middle"
                fill="white"
                fontSize="1.7"
                fontWeight="700"
              >
                {player.shirt_number}
              </text>
              {(names || active) && (
                <g className="player-name">
                  <rect x={x - 8} y={68 - y + 2.6} width="16" height="3.4" rx=".7" />
                  <text
                    x={x}
                    y={68 - y + 5}
                    textAnchor="middle"
                    fontSize="1.8"
                    fill="white"
                    direction={language === 'ar' ? 'rtl' : 'ltr'}
                  >
                    {language === 'ar' ? player.name_ar : player.short_name}
                  </text>
                </g>
              )}
              {badge && (
                <text x={x + 2.5} y={68 - y - 2.5} fontSize="2.7" fill="var(--accent)">
                  ★
                </text>
              )}
            </g>
          );
        })}
        {frame && (
          <g className="ball">
            <circle
              cx={frame.ball[0]}
              cy={68 - frame.ball[1]}
              r=".9"
              fill="white"
              stroke="#102020"
              strokeWidth=".3"
            />
            <circle cx={frame.ball[0]} cy={68 - frame.ball[1]} r=".3" fill="#102020" />
          </g>
        )}
      </svg>
      <div className="pitch-legend">
        <span>
          <i style={{ background: metadata.home.primary_color }} />
          {localizedName(metadata.home, language)}
        </span>
        <span>
          <i style={{ background: metadata.away.primary_color }} />
          {localizedName(metadata.away, language)}
        </span>
        <button className="text-button" aria-pressed={names} onClick={() => setNames(!names)}>
          {names ? copy[language].hideNames : copy[language].showNames}
        </button>
      </div>
    </div>
  );
}
