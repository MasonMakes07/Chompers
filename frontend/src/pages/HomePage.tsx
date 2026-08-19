// Home: quick search up top, full group planner below.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PartyForm } from "../components/PartyForm";
import { SearchBar } from "../components/SearchBar";
import { useParty } from "../context/PartyContext";
import { buildSearchPath } from "../searchParams";

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
      <header className="hero">
        <h1 className="hero__title">Chompers</h1>
        <p className="hero__subtitle">
          Find a spot where <em>everyone</em> can actually eat.
        </p>
      </header>

      <SearchBar size="large" onSearch={runQuickSearch} />

      <div className="divider">
        <span>or plan for the whole group</span>
      </div>

      <div className="layout layout--home">
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

        <aside className="pitch">
          <h2 className="pitch__title">Why this beats searching Maps</h2>
          <ul className="pitch__list">
            <li>
              <strong>Nobody gets averaged away.</strong> The worst-served guest
              drives 60% of the score, so one vegan outweighs four omnivores and
              a better star rating.
            </li>
            <li>
              <strong>Allergies are not diets.</strong> Thai food is great for
              vegetarians and risky for nut allergies. We score those
              separately.
            </li>
            <li>
              <strong>Every result explains itself.</strong> You see which guest
              is limiting, why, and whether it was verified or inferred.
            </li>
          </ul>
        </aside>
      </div>
    </>
  );
}
