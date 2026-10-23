import React from "react";
import { loadProfile } from "../api/client";

export default function Profile({ id }) {
  React.useEffect(() => {
    loadProfile(id).then(render);
  }, [id]);
  return null;
}

function render(user) {
  console.log(user);
}
