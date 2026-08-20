// Home: brand bar with quick search, hero, group planner, and explainer.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PartyForm } from "../components/PartyForm";
import { SearchBar } from "../components/SearchBar";
import { useParty } from "../context/PartyContext";
import { buildSearchPath } from "../searchParams";

const STEPS = [
  {
    title: "Add anyone with a restriction",
    body: "Allergies, vegan, halal, gluten-free — just the people who need it.",
  },
  {
    title: "Drop a location",
    body: "Use your current spot or type any city or ZIP code.",
  },
  {
    title: "Get five that fit everyone",
    body: "We rank nearby options by group fit, cuisine and distance.",
  },
];

export function HomePage() {
  const navigate = useNavigate();
  const {
    guestCount,
    guests,
    coordinates,
    setGuestCount,
    setGuests,
    setCoordinates,
  } = useParty();

  const [locationQuery, setLocationQuery] = useState("");
  const [radiusMeters, setRadiusMeters] = useState(5000);
  const [maxPriceLevel, setMaxPriceLevel] = useState<number | null>(null);

  // Sends a quick keyword search to the results page.
  const runQuickSearch = (query: string, quickLocation: string) => {
    navigate(
      buildSearchPath({
        query,
        locationQuery: quickLocation,
        coordinates,
        radiusMeters,
        maxPriceLevel,
      })
    );
  };

  // Sends the full party search to the results page, with no keyword.
  const runPartySearch = () => {
    navigate(
      buildSearchPath({
        query: "",
        locationQuery,
        coordinates,
        radiusMeters,
        maxPriceLevel,
      })
    );
  };

  return (
    <>
      <header className="topbar">
        <span className="brand">Chompers</span>
        <div className="topbar__search">
          <SearchBar onSearch={runQuickSearch} />
        </div>
      </header>

      <div className="hero">
        <svg
          className="hero__art"
          viewBox="0 0 200 140"
          role="img"
          aria-label="A group sharing a meal everyone can eat"
        >
          {/* Plate */}
          <ellipse
            cx="100"
            cy="98"
            rx="62"
            ry="22"
            fill="#eef2ec"
            stroke="#3f5a45"
            strokeWidth="3"
          />
          <ellipse cx="100" cy="95" rx="43" ry="14" fill="#dbe6dd" />
          {/* Three heads, one group */}
          <circle cx="70" cy="48" r="16" fill="#d9b354" />
          <circle cx="100" cy="40" r="18" fill="#3f5a45" />
          <circle cx="130" cy="48" r="16" fill="#b58575" />
          {/* "Everyone's good" check */}
          <circle cx="152" cy="30" r="14" fill="#3f5a45" />
          <path
            d="M145 30l5 6 9-11"
            stroke="#fff"
            strokeWidth="3"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <h1 className="hero__title">Eat together, no compromises</h1>
        <p className="hero__subtitle">
          Find a spot where <em>everyone</em> can actually eat — or use quick
          search above to browse.
        </p>
      </div>

      <div className="layout">
        <PartyForm
          guestCount={guestCount}
          guests={guests}
          coordinates={coordinates}
          locationQuery={locationQuery}
          radiusMeters={radiusMeters}
          maxPriceLevel={maxPriceLevel}
          isSearching={false}
          onGuestCountChange={setGuestCount}
          onGuestsChange={setGuests}
          onCoordinatesChange={setCoordinates}
          onLocationQueryChange={setLocationQuery}
          onRadiusChange={setRadiusMeters}
          onMaxPriceChange={setMaxPriceLevel}
          onSubmit={runPartySearch}
        />

        <aside className="card">
          <h2 className="explainer__title">One search, everyone eats</h2>
          <p className="explainer__lead">
            Add your group, note who has restrictions, pick a location — we rank
            the five best nearby spots that work for <em>everyone</em> at once.
          </p>

          <ol className="steps">
            {STEPS.map((step, index) => (
              <li key={step.title} className="step">
                <span className="step__num">{index + 1}</span>
                <div>
                  <p className="step__title">{step.title}</p>
                  <p className="step__body">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </>
  );
}
