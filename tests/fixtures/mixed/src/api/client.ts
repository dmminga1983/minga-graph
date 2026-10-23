import { formatUser, type User } from "../util/format";
import axios from "axios";

/** HTTP client for the users API. */
export class ApiClient extends BaseClient implements Disposable {
  private base: string;
  constructor(base: string) {
    super();
    this.base = base;
  }

  async getUser(id: number): Promise<User> {
    const res = await axios.get(`${this.base}/users/${id}`); // "not a call(" in string
    return this.normalize(res.data);
  }

  normalize(raw: any): User {
    return formatUser(raw);
  }

  dispose(): void {}
}

export class BaseClient {
  ping() { return true; }
}

export const loadProfile = async (id: number) => {
  const c = new ApiClient("/api");
  return c.getUser(id);
};
